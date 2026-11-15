"""RQ1 (M1): why self-checks were fooled, from labels only.

A self-check false positive is a sampled trajectory that passed its own self-check and is not
resolved (every sampled trajectory is unresolved). Its label carries a `fooled_reason`. This
counts those reasons over the labeled false positives, with Wilson 95% intervals (one trajectory
per instance, so items are independent), and keeps up to 3 notes per reason as examples for the
write-up.

    python -m grader_proof.rq1 --labels labels/opus_test.jsonl --out results/rq1
"""

import argparse
import csv
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from grader_proof.labeling import (
    FOOLED_REASONS,
    SAMPLE_PATH,
    Label,
    SampleItem,
    check_fooled_reason,
    read_labels,
    read_sample,
)
from grader_proof.stats import wilson_interval

EXAMPLES_PER_REASON = 3


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ReasonRow(Frozen):
    reason: str
    description: str
    count: int
    share: float
    low: float
    high: float


class Rq1(Frozen):
    labeled: int
    with_self_check: int
    false_positives: int
    rows: list[ReasonRow]
    examples: dict[str, list[Label]]


def summarize(labels: Sequence[Label], sample: Sequence[SampleItem]) -> Rq1:
    """Counts fooled reasons over the labeled self-check false positives.

    Raises ValueError, naming every bad label, if a label is not in the sample, or breaks the
    rule that self-check false positives, and only they, take a fooled_reason.
    """
    if not labels:
        raise ValueError("no labels to summarize")
    items = {item.trajectory_id: item for item in sample}
    problems: list[str] = []
    for label in labels:
        item = items.get(label.trajectory_id)
        if item is None:
            problems.append(f"{label.trajectory_id}: not in the sample")
            continue
        try:
            check_fooled_reason(label, item)
        except ValueError as error:
            problems.append(f"{label.trajectory_id}: {error}")
    if problems:
        raise ValueError("\n".join(problems))

    fooled = sorted(
        (label for label in labels if label.fooled_reason is not None),
        key=lambda label: label.trajectory_id,
    )
    rows: list[ReasonRow] = []
    for reason, description in FOOLED_REASONS.items():
        count = sum(label.fooled_reason == reason for label in fooled)
        low, high = wilson_interval(count, len(fooled)) if fooled else (0.0, 0.0)
        rows.append(
            ReasonRow(
                reason=reason,
                description=description,
                count=count,
                share=count / len(fooled) if fooled else 0.0,
                low=low,
                high=high,
            )
        )
    return Rq1(
        labeled=len(labels),
        with_self_check=sum(
            items[label.trajectory_id].self_check_passed is not None for label in labels
        ),
        false_positives=len(fooled),
        rows=rows,
        examples={
            reason: [label for label in fooled if label.fooled_reason == reason][
                :EXAMPLES_PER_REASON
            ]
            for reason in FOOLED_REASONS
        },
    )


def write_csv(rq1: Rq1, path: Path) -> None:
    with path.open("w", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(
            ["fooled_reason", "count", "false_positives", "share", "share_low", "share_high"]
        )
        for r in rq1.rows:
            writer.writerow(
                [
                    r.reason,
                    r.count,
                    rq1.false_positives,
                    f"{r.share:.4g}",
                    f"{r.low:.4g}",
                    f"{r.high:.4g}",
                ]
            )


def render_markdown(rq1: Rq1, source: Path) -> str:
    lines = [
        "# RQ1: why self-checks were fooled",
        "",
        f"From `{source}`: {rq1.labeled} labeled unresolved trajectories, {rq1.with_self_check} "
        f"with a self-check, {rq1.false_positives} that passed it (self-check false positives).",
        "",
        "| Reason | What it means | Count | Share [95% Wilson interval] |",
        "|---|---|---|---|",
        *(
            f"| {r.reason} | {r.description} | {r.count} "
            f"| {r.share:.0%} [{r.low:.0%}, {r.high:.0%}] |"
            for r in rq1.rows
        ),
        "",
        "## Examples (labelers' notes, up to 3 per reason)",
    ]
    for reason, examples in rq1.examples.items():
        lines += ["", f"### {reason}", ""]
        lines += [f"- {label.trajectory_id}: {label.note}" for label in examples] or ["- none"]
    return "\n".join(lines) + "\n" + OPEN_QUESTION_6


# Open question 6 in design.md, answered as far as the data allows.
OPEN_QUESTION_6 = """
## Broke a PASS_TO_PASS test or missed a FAIL_TO_PASS test?

The data cannot say. The trajectories dataset records the upstream outcome only as
`resolved`, `gen_tests_correct` and `pred_passes_gen_tests`, one value per trajectory, with no
per-test results. Telling the two apart needs the upstream tests rerun on each sampled patch in
its instance's image (design.md, open question 6).
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=Path("labels/opus_test.jsonl"))
    parser.add_argument("--sample", type=Path, default=SAMPLE_PATH)
    parser.add_argument("--out", type=Path, default=Path("results/rq1"), help="writes .csv and .md")
    args = parser.parse_args()
    if not args.labels.exists():
        raise SystemExit(f"{args.labels} does not exist")
    try:
        rq1 = summarize(read_labels(args.labels), read_sample(args.sample))
    except ValueError as error:
        raise SystemExit(f"{args.labels}:\n{error}") from error
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_csv(rq1, args.out.with_suffix(".csv"))
    table = render_markdown(rq1, args.labels)
    args.out.with_suffix(".md").write_text(table)
    print(table)


if __name__ == "__main__":
    main()
