"""Estimates how common each failure class is, from the frozen triager on 1,000 more trajectories.

Run with `make triage-prevalence` (#15). It draws 1,000 unresolved trajectories with a fixed seed,
outside the 100-item labeling sample, and keeps the draw in results/prevalence_sample.jsonl so
reruns use the same items. The triager (rules, then the frozen judge) classifies each one, and the
share of each class gets a 95% bootstrap interval that resamples instances, because trajectories
of one instance are correlated. Judge calls are cached (ADR 0004), so a rerun costs nothing.

These are a classifier's estimates. Read them next to the triager's confusion matrix on the test
labels (`make triage-eval`).
"""

import random
import sys
from collections.abc import Collection, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from grader_proof.judge import FROZEN_VERSION
from grader_proof.label_cli import unresolved_candidates
from grader_proof.labeling import FAILURE_CLASSES, SAMPLE_PATH, Candidate, read_sample
from grader_proof.llm import CachedClient
from grader_proof.stats import bootstrap_ci
from grader_proof.tinker_transport import TinkerTransport
from grader_proof.triage_eval import judge_dollars, predictions, run_triager

DRAW_PATH = Path("results/prevalence_sample.jsonl")
RESULTS_PATH = Path("results/triage_prevalence.json")
NOTE_PATH = Path("results/triage_prevalence.md")
DRAW_SEED = 15
DRAW_SIZE = 1000
BOOTSTRAP_SEED = 0


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Share(Frozen):
    """count / n with its 95% bootstrap interval, resampling instances."""

    count: int
    share: float
    low: float
    high: float


class Report(Frozen):
    trajectories: int
    instances: int
    draw_seed: int
    frozen_version: str
    rules_fired: int
    judge_outcomes: dict[str, int]
    judge_prompt_tokens: int
    judge_completion_tokens: int
    judge_dollars: float
    shares: dict[str, Share]


def draw_prevalence_sample(
    candidates: Sequence[Candidate], labeled: Collection[str], seed: int, size: int
) -> list[Candidate]:
    """`size` trajectories drawn uniformly from the candidates whose ids are not in `labeled`."""
    pool = sorted(
        (c for c in candidates if c.trajectory_id not in labeled), key=lambda c: c.trajectory_id
    )
    if len(pool) < size:
        raise ValueError(f"only {len(pool)} candidates outside the labeled sample, need {size}")
    return random.Random(seed).sample(pool, size)


def class_shares(classes: Sequence[str], instances: Sequence[str]) -> dict[str, Share]:
    """The share of each failure class, in precedence order, with an instance-clustered interval."""
    shares: dict[str, Share] = {}
    for c in FAILURE_CLASSES:
        count = sum(found == c for found in classes)

        def share_of(sample: Sequence[str], c: str = c) -> float:
            return sum(found == c for found in sample) / len(sample)

        low, high = bootstrap_ci(classes, share_of, seed=BOOTSTRAP_SEED, clusters=instances)
        shares[c] = Share(count=count, share=count / len(classes), low=low, high=high)
    return shares


def load_or_draw() -> list[Candidate]:
    if DRAW_PATH.exists():
        return [Candidate.model_validate_json(line) for line in DRAW_PATH.read_text().splitlines()]
    labeled = {item.trajectory_id for item in read_sample(SAMPLE_PATH)}
    drawn = draw_prevalence_sample(unresolved_candidates(), labeled, DRAW_SEED, DRAW_SIZE)
    DRAW_PATH.parent.mkdir(exist_ok=True)
    DRAW_PATH.write_text("".join(c.model_dump_json() + "\n" for c in drawn))
    return drawn


def note(report: Report) -> str:
    rows = "\n".join(
        f"| `{c}` | {s.count} | {s.share:.1%} | {s.low:.1%} to {s.high:.1%} |"
        for c, s in report.shares.items()
    )
    return f"""# Failure class prevalence (issue #15)

These are estimates from the triager, not hand labels. The triager makes mistakes, and its
confusion matrix on the 70 test labels (`make triage-eval`, issue #14) belongs next to this
table: a class the triager over-predicts there is over-counted here too.

{report.trajectories} unresolved trajectories from {report.instances} instances, drawn with seed
{report.draw_seed} outside the labeling sample. The rules fired on {report.rules_fired}; the judge
(`{report.frozen_version}`) classified the rest. Intervals are 95% bootstrap intervals that
resample instances.

| Class | Trajectories | Share | 95% interval |
|---|---|---|---|
{rows}

Judge outcomes: {report.judge_outcomes}. Judge tokens: {report.judge_prompt_tokens:,} prompt,
{report.judge_completion_tokens:,} completion, ${report.judge_dollars:.2f} at list price.
"""


def main() -> None:
    items = load_or_draw()
    ran = run_triager(CachedClient(TinkerTransport()), items)
    if ran is None:
        sys.exit("Batch declined; nothing written.")
    verdicts, results = ran
    classes = [p.failure_class for p in predictions(verdicts, results)]
    report = Report(
        trajectories=len(items),
        instances=len({item.instance_id for item in items}),
        draw_seed=DRAW_SEED,
        frozen_version=FROZEN_VERSION,
        rules_fired=sum(v is not None for v in verdicts),
        judge_outcomes={
            o: sum(r.outcome == o for r in results) for o in ("parsed", "repaired", "failed")
        },
        judge_prompt_tokens=sum(r.prompt_tokens for r in results),
        judge_completion_tokens=sum(r.completion_tokens for r in results),
        judge_dollars=judge_dollars(results),
        shares=class_shares(classes, [item.instance_id for item in items]),
    )
    RESULTS_PATH.write_text(report.model_dump_json(indent=1) + "\n")
    NOTE_PATH.write_text(note(report))
    print(note(report))


if __name__ == "__main__":
    main()
