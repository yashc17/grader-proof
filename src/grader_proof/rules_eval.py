"""Scores the triage rules on the dev labels and writes results/rules_dev.json.

Run with `make rules-dev`. Only dev items are used: the loader keeps the dev items of
labels/sample.jsonl first and reads a label line only when its trajectory is one of them, so the
test labels are never parsed (ADR 0003: rules are tuned on dev, kappa is reported once on test).
"""

import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import polars as pl
from pydantic import BaseModel, ConfigDict

from grader_proof.label_cli import TRAJECTORIES
from grader_proof.labeling import (
    LABELS_PATH,
    SAMPLE_PATH,
    Candidate,
    Label,
    SampleItem,
    Split,
    read_sample,
)
from grader_proof.stats import wilson_interval
from grader_proof.trajectory import Trajectory
from grader_proof.triage_rules import RULES, Verdict, triage

RESULTS_PATH = Path("results/rules_dev.json")


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Proportion(Frozen):
    """successes / n with its 95% Wilson interval."""

    successes: int
    n: int
    rate: float
    low: float
    high: float


class RuleScore(Frozen):
    fired: int
    correct: int


class Report(Frozen):
    items: int
    fired: int
    correct: int
    coverage: Proportion
    precision: Proportion | None
    rules: dict[str, RuleScore]
    labels: dict[str, int]


def proportion(successes: int, n: int) -> Proportion:
    low, high = wilson_interval(successes, n)
    return Proportion(successes=successes, n=n, rate=successes / n, low=low, high=high)


def load_labeled_items(
    sample_path: Path, labels_path: Path, split: Split
) -> list[tuple[SampleItem, Label]]:
    """The split's items with their labels. Label lines of any other trajectory are skipped
    unparsed. Raises ValueError if an item of the split has no label yet."""
    if not labels_path.exists():
        raise FileNotFoundError(
            f"{labels_path} not found. It holds hand labels, which are not in the repository; "
            "copy it from the labeler's checkout to run this target."
        )
    chosen = {item.trajectory_id: item for item in read_sample(sample_path) if item.split == split}
    labels: dict[str, Label] = {}
    for line in labels_path.read_text().splitlines():
        if json.loads(line)["trajectory_id"] in chosen:
            label = Label.model_validate_json(line)
            labels[label.trajectory_id] = label
    missing = sorted(set(chosen) - set(labels))
    if missing:
        raise ValueError(f"{split} items without a label: {', '.join(missing)}")
    return [(item, labels[trajectory_id]) for trajectory_id, item in chosen.items()]


def load_dev_items(sample_path: Path, labels_path: Path) -> list[tuple[SampleItem, Label]]:
    return load_labeled_items(sample_path, labels_path, "dev")


def evaluate(pairs: Sequence[tuple[Label, Verdict | None]]) -> Report:
    """Coverage is the share of items where a rule fired; precision the share of those correct."""
    fired = [(label, verdict) for label, verdict in pairs if verdict is not None]
    correct = [(label, v) for label, v in fired if v.failure_class == label.failure_class]
    rules = {
        rule.__name__: RuleScore(
            fired=sum(v.rule == rule.__name__ for _, v in fired),
            correct=sum(v.rule == rule.__name__ for _, v in correct),
        )
        for rule in RULES
    }
    return Report(
        items=len(pairs),
        fired=len(fired),
        correct=len(correct),
        coverage=proportion(len(fired), len(pairs)),
        precision=proportion(len(correct), len(fired)) if fired else None,
        rules=rules,
        labels=dict(Counter(label.failure_class for label, _ in pairs)),
    )


def load_trajectories(items: Sequence[Candidate]) -> dict[str, Trajectory]:
    ids = [item.trajectory_id for item in items]
    rows = pl.scan_parquet(TRAJECTORIES).filter(pl.col("trajectory_id").is_in(ids)).collect()
    return {row["trajectory_id"]: Trajectory.from_row(row) for row in rows.iter_rows(named=True)}


def main() -> None:
    try:
        dev = load_dev_items(SAMPLE_PATH, LABELS_PATH)
    except FileNotFoundError as error:
        sys.exit(str(error))
    trajectories = load_trajectories([item for item, _ in dev])
    report = evaluate([(label, triage(trajectories[item.trajectory_id])) for item, label in dev])
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(report.model_dump_json(indent=1) + "\n")
    print(report.model_dump_json(indent=1))


if __name__ == "__main__":
    main()
