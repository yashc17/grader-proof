"""How well two label files agree: self-agreement (#10) and Opus against the maintainer (ADR 0015).

Compares only the trajectories labeled in both files. For failure classes it reports Cohen's
kappa with its 95% bootstrap interval and the share that agree with its Wilson 95% interval,
over the items neither file calls `unclear`; those are counted apart (ADR 0003). It lists every
pair of classes the two files disagree on. For fooled reasons it scores the items where both
files gave one, and counts the items where only one did.

    python -m grader_proof.label_agreement --a A.jsonl --b B.jsonl --name NAME
"""

import argparse
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from grader_proof.judge_eval import KappaScore, score
from grader_proof.labeling import SAMPLE_PATH, Label, SampleItem, read_labels, read_sample
from grader_proof.stats import wilson_interval


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ReasonAgreement(Frozen):
    both: KappaScore
    only_a: int
    only_b: int


class AgreementReport(Frozen):
    shared: int
    only_in_a: int
    only_in_b: int
    # `human_unclear` counts file A's `unclear` labels and `triager_unclear` file B's.
    failure_class: KappaScore
    agreement_interval: tuple[float, float] | None
    disagreements: dict[str, int]
    fooled_reason: ReasonAgreement


def _by_id(name: str, labels: Sequence[Label], sample_ids: set[str]) -> dict[str, Label]:
    problems: list[str] = []
    for trajectory_id, count in sorted(Counter(label.trajectory_id for label in labels).items()):
        if trajectory_id not in sample_ids:
            problems.append(f"{name}: {trajectory_id} not in the sample")
        if count > 1:
            problems.append(f"{name}: {trajectory_id} labeled more than once")
    if problems:
        raise ValueError("\n".join(problems))
    return {label.trajectory_id: label for label in labels}


def compare(
    a: Sequence[Label], b: Sequence[Label], sample: Sequence[SampleItem]
) -> AgreementReport:
    """Raises ValueError if a file names a trajectory outside the sample or one twice, or if no
    trajectory is labeled in both."""
    sample_ids = {item.trajectory_id for item in sample}
    by_a, by_b = _by_id("A", a, sample_ids), _by_id("B", b, sample_ids)
    shared = sorted(by_a.keys() & by_b.keys())
    if not shared:
        raise ValueError("no trajectory is labeled in both files")

    classes = [(by_a[t].failure_class, by_b[t].failure_class) for t in shared]
    failure_class = score(classes)
    agreeing = sum(x == y for x, y in classes if "unclear" not in (x, y))
    reasons = [(by_a[t].fooled_reason, by_b[t].fooled_reason) for t in shared]
    return AgreementReport(
        shared=len(shared),
        only_in_a=len(by_a.keys() - by_b.keys()),
        only_in_b=len(by_b.keys() - by_a.keys()),
        failure_class=failure_class,
        agreement_interval=wilson_interval(agreeing, failure_class.scored)
        if failure_class.scored
        else None,
        disagreements=dict(sorted(Counter(f"{x} -> {y}" for x, y in classes if x != y).items())),
        fooled_reason=ReasonAgreement(
            both=score([(x, y) for x, y in reasons if x is not None and y is not None]),
            only_a=sum(x is not None and y is None for x, y in reasons),
            only_b=sum(x is None and y is not None for x, y in reasons),
        ),
    )


def _row(name: str, s: KappaScore, interval: tuple[float, float] | None = None) -> str:
    if s.agreement is None or s.kappa is None:
        return f"| {name} | 0 | none scored | |"
    agreeing = round(s.agreement * s.scored)
    share = f"{agreeing}/{s.scored} = {s.agreement:.0%}"
    if interval is not None:
        share += f" [{interval[0]:.0%}, {interval[1]:.0%}]"
    return f"| {name} | {s.scored} | {share} | {s.kappa:.3f} [{s.low:.3f}, {s.high:.3f}] |"


def render_markdown(report: AgreementReport, a: Path, b: Path) -> str:
    fc, reasons = report.failure_class, report.fooled_reason
    pairs = [
        f"| {pair.split(' -> ')[0]} | {pair.split(' -> ')[1]} | {count} |"
        for pair, count in report.disagreements.items()
    ]
    lines = [
        "# Label agreement",
        "",
        f"A = `{a}`, B = `{b}`. {report.shared} trajectories are labeled in both "
        f"({report.only_in_a} only in A, {report.only_in_b} only in B, not compared).",
        "",
        "| Field | Scored | Agree [95% Wilson interval] | Cohen's κ [95% bootstrap interval] |",
        "|---|---|---|---|",
        _row("Failure class", fc, report.agreement_interval),
        _row("Fooled reason", reasons.both),
        "",
        f"Failure class: items either file calls `unclear` are left out (ADR 0003): "
        f"A {fc.human_unclear}, B {fc.triager_unclear}.",
        f"Fooled reason: scored where both files gave one; "
        f"only A gave one: {reasons.only_a}, only B gave one: {reasons.only_b}.",
        "",
        "## Failure classes the files disagree on",
        "",
        "| A | B | Count |",
        "|---|---|---|",
        *(pairs or ["| none | | |"]),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    parser.add_argument("--name", required=True, help="output stem: results/agreement_<name>")
    parser.add_argument("--sample", type=Path, default=SAMPLE_PATH)
    parser.add_argument("--out-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    for path in (args.a, args.b):
        if not path.exists():
            raise SystemExit(f"{path} does not exist")
    try:
        report = compare(read_labels(args.a), read_labels(args.b), read_sample(args.sample))
    except ValueError as error:
        raise SystemExit(str(error)) from error
    out = args.out_dir / f"agreement_{args.name}"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(report.model_dump_json(indent=2) + "\n")
    table = render_markdown(report, args.a, args.b)
    out.with_suffix(".md").write_text(table)
    print(table)


if __name__ == "__main__":
    main()
