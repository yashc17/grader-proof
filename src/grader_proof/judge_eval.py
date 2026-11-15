"""Scores every judge prompt version on the dev labels and writes results/judge_dev.json.

Run with `make judge-dev`. For each prompt version in `judge_prompts/` it reports Cohen's kappa
twice: for the triager (rules first, the judge on what they abstain on) over all dev items, and for
the judge alone over the items the rules abstain on. `unclear` on either side is left out of kappa
and counted (ADR 0003). Only dev items are loaded, through `rules_eval.load_dev_items`, so the
test labels are never read. Calls are cached, so rerunning costs nothing.
"""

import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict

from grader_proof.judge import (
    FROZEN_VERSION,
    JUDGE_MODEL,
    JudgeResult,
    judge_all,
    judge_input,
    load_prompt,
    prompt_versions,
)
from grader_proof.label_cli import SWE_REBENCH
from grader_proof.labeling import LABELS_PATH, SAMPLE_PATH, Candidate
from grader_proof.llm import PRICES, CachedClient
from grader_proof.rules_eval import load_dev_items, load_trajectories
from grader_proof.stats import bootstrap_ci, cohens_kappa
from grader_proof.tinker_transport import TinkerTransport
from grader_proof.triage_rules import Verdict, triage

RESULTS_PATH = Path("results/judge_dev.json")
BOOTSTRAP_SEED = 0


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class KappaScore(Frozen):
    """Kappa over the items neither side calls `unclear`, with its 95% bootstrap interval."""

    items: int
    scored: int
    human_unclear: int
    triager_unclear: int
    agreement: float | None
    kappa: float | None
    low: float | None
    high: float | None
    confusion: dict[str, int]  # "human -> predicted": count, over all items


class VersionReport(Frozen):
    version: str
    triager: KappaScore
    judge_alone: KappaScore
    outcomes: dict[str, int]
    prompt_tokens: int
    completion_tokens: int
    dollars: float


class Report(Frozen):
    items: int
    rules_fired: int
    labels: dict[str, int]
    frozen_version: str
    versions: list[VersionReport]


def score(pairs: Sequence[tuple[str, str]]) -> KappaScore:
    """Scores (human, predicted) pairs."""
    kept = [(human, predicted) for human, predicted in pairs if "unclear" not in (human, predicted)]

    def kappa(sample: Sequence[tuple[str, str]]) -> float:
        return cohens_kappa([h for h, _ in sample], [p for _, p in sample])

    estimate = low = high = agreement = None
    if kept:
        estimate = kappa(kept)
        low, high = bootstrap_ci(kept, kappa, seed=BOOTSTRAP_SEED)
        agreement = sum(h == p for h, p in kept) / len(kept)
    return KappaScore(
        items=len(pairs),
        scored=len(kept),
        human_unclear=sum(h == "unclear" for h, _ in pairs),
        triager_unclear=sum(p == "unclear" for _, p in pairs),
        agreement=agreement,
        kappa=estimate,
        low=low,
        high=high,
        confusion=dict(sorted(Counter(f"{h} -> {p}" for h, p in pairs).items())),
    )


def combine(rule_verdicts: Sequence[Verdict | None], judge_classes: Sequence[str]) -> list[str]:
    """The rule's class where a rule fired; the judge's, in order, where every rule abstained."""
    if sum(v is None for v in rule_verdicts) != len(judge_classes):
        raise ValueError("need exactly one judge class per rule abstention")
    judged = iter(judge_classes)
    return [next(judged) if v is None else v.failure_class for v in rule_verdicts]


def load_tasks(items: Sequence[Candidate]) -> dict[str, dict[str, Any]]:
    ids = list({item.instance_id for item in items})
    rows = (
        pl.scan_parquet(SWE_REBENCH)
        .filter(pl.col("instance_id").is_in(ids))
        .select("instance_id", "problem_statement", "patch", "FAIL_TO_PASS")
        .collect()
    )
    return {row["instance_id"]: row for row in rows.iter_rows(named=True)}


def version_report(
    version: str,
    humans: Sequence[str],
    rule_verdicts: Sequence[Verdict | None],
    results: Sequence[JudgeResult],
) -> VersionReport:
    judged = [r.verdict.failure_class for r in results]
    abstained = [h for h, v in zip(humans, rule_verdicts, strict=True) if v is None]
    price = PRICES[JUDGE_MODEL]
    prompt_tokens = sum(r.prompt_tokens for r in results)
    completion_tokens = sum(r.completion_tokens for r in results)
    return VersionReport(
        version=version,
        triager=score(list(zip(humans, combine(rule_verdicts, judged), strict=True))),
        judge_alone=score(list(zip(abstained, judged, strict=True))),
        outcomes=dict(Counter(r.outcome for r in results)),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        dollars=(prompt_tokens * price.prefill + completion_tokens * price.sample) / 1e6,
    )


def describe(result: KappaScore) -> str:
    if result.kappa is None:
        return f"no scorable items ({result.items} items)"
    return (
        f"kappa {result.kappa:.2f} [{result.low:.2f}, {result.high:.2f}] on {result.scored} "
        f"items, agreement {result.agreement:.0%}, unclear: human {result.human_unclear}, "
        f"triager {result.triager_unclear}"
    )


def main() -> None:
    try:
        dev = load_dev_items(SAMPLE_PATH, LABELS_PATH)
    except FileNotFoundError as error:
        sys.exit(str(error))
    items = [item for item, _ in dev]
    humans = [label.failure_class for _, label in dev]
    trajectories = load_trajectories(items)
    rule_verdicts = [triage(trajectories[item.trajectory_id]) for item in items]
    tasks = load_tasks(items)
    inputs = [
        judge_input(
            trajectories[item.trajectory_id],
            issue=tasks[item.instance_id]["problem_statement"],
            gold_patch=tasks[item.instance_id]["patch"],
            fail_to_pass=tasks[item.instance_id]["FAIL_TO_PASS"],
        )
        for item, verdict in zip(items, rule_verdicts, strict=True)
        if verdict is None
    ]

    client = CachedClient(TinkerTransport())
    reports: list[VersionReport] = []
    for version in prompt_versions():
        print(f"\n{version}: judging {len(inputs)} items the rules abstain on")
        results = judge_all(client, inputs, load_prompt(version))
        if results is None:
            sys.exit("Batch declined; nothing written.")
        report = version_report(version, humans, rule_verdicts, results)
        reports.append(report)
        print(f"  triager:     {describe(report.triager)}")
        print(f"  judge alone: {describe(report.judge_alone)}")
        print(f"  outcomes: {report.outcomes}, cost ${report.dollars:.3f}")

    report = Report(
        items=len(dev),
        rules_fired=sum(v is not None for v in rule_verdicts),
        labels=dict(Counter(humans)),
        frozen_version=FROZEN_VERSION,
        versions=reports,
    )
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(report.model_dump_json(indent=1) + "\n")
    print(f"\nwrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
