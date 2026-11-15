"""Scores the frozen triager on the 70 test labels and writes results/triage_test.json (#14).

Run with `make triage-eval`, once, after every test item has a label. The labels come from the
file `--labels` names, by default the Claude Opus 5.5 labeler session's `labels/opus_test.jsonl`;
the report's header names the labeler. The triager is the rules, then the frozen judge prompt on
every item the rules abstain on. The report holds Cohen's kappa with its 95% bootstrap interval,
the confusion matrix, precision and recall per class, two baselines (the rules alone and always
the most common class), the rules' coverage and their precision on the items they fire on, and
every disagreement with the triager's evidence. `unclear` on either side is left out of kappa and
counted (ADR 0003).

The target refuses to run while any test item lacks a label, so no prediction for a test item
exists before the labels are final.
"""

import argparse
import hashlib
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from grader_proof.judge import (
    FROZEN_SHA256,
    FROZEN_VERSION,
    JUDGE_MODEL,
    JudgeResult,
    judge_all,
    judge_input,
    load_prompt,
)
from grader_proof.judge_eval import KappaScore, load_tasks, score
from grader_proof.labeling import FAILURE_CLASSES, SAMPLE_PATH, Candidate, Label
from grader_proof.llm import PRICES, CachedClient, ask_on_terminal
from grader_proof.rules_eval import Report as RulesReport
from grader_proof.rules_eval import evaluate as evaluate_rules
from grader_proof.rules_eval import load_labeled_items, load_trajectories
from grader_proof.tinker_transport import TinkerTransport
from grader_proof.triage_rules import Verdict, triage

RESULTS_PATH = Path("results/triage_test.json")
LABELS_PATH = Path("labels/opus_test.jsonl")
LABELER = "Claude Opus 5.5 labeler session"
# The rules-alone baseline's class for an item every rule abstains on. It never matches a label.
ABSTAIN = "abstain"
SCORED_CLASSES = [c for c in FAILURE_CLASSES if c != "unclear"]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Prediction(Frozen):
    """The triager's class for one item, with the rule or judge evidence behind it."""

    failure_class: str
    source: str  # "rule:<name>" or "judge"
    evidence: str
    confidence: float | None


class ClassScore(Frozen):
    true_positives: int
    predicted: int
    actual: int
    precision: float | None  # None when the class is never predicted
    recall: float | None  # None when no label has the class


class Disagreement(Frozen):
    trajectory_id: str
    instance_id: str
    labeled: str
    note: str
    predicted: str
    source: str
    evidence: str
    confidence: float | None


class Report(Frozen):
    labeler: str
    label_file: str
    items: int
    labels: dict[str, int]
    frozen_version: str
    triager: KappaScore
    classes: dict[str, ClassScore]
    rules_alone: KappaScore
    rules: RulesReport  # coverage, and precision on the items a rule fires on
    majority_class: str
    majority: KappaScore
    self_agreement: KappaScore | None  # from the maintainer's re-labels (#10), once they exist
    judge_outcomes: dict[str, int]
    judge_dollars: float
    disagreements: list[Disagreement]


def run_triager(
    client: CachedClient,
    items: Sequence[Candidate],
    confirm: Callable[[], bool] = ask_on_terminal,
) -> tuple[list[Verdict | None], list[JudgeResult]] | None:
    """The rules on every item, then the frozen judge on the items they abstain on, in order.

    Returns None if a model batch is declined.
    """
    prompt = load_prompt(FROZEN_VERSION)
    if hashlib.sha256(prompt.text.encode()).hexdigest() != FROZEN_SHA256:
        raise RuntimeError(f"{FROZEN_VERSION} changed after it was frozen")
    trajectories = load_trajectories(items)
    tasks = load_tasks(items)
    verdicts = [triage(trajectories[item.trajectory_id]) for item in items]
    inputs = [
        judge_input(
            trajectories[item.trajectory_id],
            issue=tasks[item.instance_id]["problem_statement"],
            gold_patch=tasks[item.instance_id]["patch"],
            fail_to_pass=tasks[item.instance_id]["FAIL_TO_PASS"],
        )
        for item, verdict in zip(items, verdicts, strict=True)
        if verdict is None
    ]
    print(f"rules fired on {len(items) - len(inputs)} of {len(items)} items; judging the rest")
    results = judge_all(client, inputs, prompt, confirm)
    return None if results is None else (verdicts, results)


def predictions(
    rule_verdicts: Sequence[Verdict | None], judge_results: Sequence[JudgeResult]
) -> list[Prediction]:
    """The rule's verdict where a rule fired; the judge's, in order, where every rule abstained."""
    if sum(v is None for v in rule_verdicts) != len(judge_results):
        raise ValueError("need exactly one judge result per rule abstention")
    judged = iter(judge_results)
    found: list[Prediction] = []
    for verdict in rule_verdicts:
        if verdict is None:
            judge = next(judged).verdict
            found.append(
                Prediction(
                    failure_class=judge.failure_class,
                    source="judge",
                    evidence=judge.evidence,
                    confidence=judge.confidence,
                )
            )
        else:
            found.append(
                Prediction(
                    failure_class=verdict.failure_class,
                    source=f"rule:{verdict.rule}",
                    evidence=verdict.evidence,
                    confidence=None,
                )
            )
    return found


def rules_alone(rule_verdicts: Sequence[Verdict | None]) -> list[str]:
    return [ABSTAIN if v is None else v.failure_class for v in rule_verdicts]


def majority_baseline(humans: Sequence[str]) -> list[str]:
    """The most common human class other than `unclear`, for every item. Ties go to the class
    first in precedence order."""
    counts = Counter(h for h in humans if h != "unclear")
    majority = max(SCORED_CLASSES, key=lambda c: (counts[c], -SCORED_CLASSES.index(c)))
    return [majority] * len(humans)


def class_scores(pairs: Sequence[tuple[str, str]]) -> dict[str, ClassScore]:
    """Precision and recall of each class over (human, predicted) pairs."""
    scores: dict[str, ClassScore] = {}
    for c in SCORED_CLASSES:
        hits = sum(h == p == c for h, p in pairs)
        predicted = sum(p == c for _, p in pairs)
        actual = sum(h == c for h, _ in pairs)
        scores[c] = ClassScore(
            true_positives=hits,
            predicted=predicted,
            actual=actual,
            precision=hits / predicted if predicted else None,
            recall=hits / actual if actual else None,
        )
    return scores


def judge_dollars(results: Sequence[JudgeResult]) -> float:
    """List-price cost of the judge's tokens, cached calls included."""
    price = PRICES[JUDGE_MODEL]
    prompt = sum(r.prompt_tokens for r in results)
    completion = sum(r.completion_tokens for r in results)
    return (prompt * price.prefill + completion * price.sample) / 1e6


def evaluate(
    items: Sequence[Candidate],
    labels: Sequence[Label],
    rule_verdicts: Sequence[Verdict | None],
    judge_results: Sequence[JudgeResult],
    labeler: str,
    label_file: str,
) -> Report:
    humans = [label.failure_class for label in labels]
    found = predictions(rule_verdicts, judge_results)
    pairs = list(zip(humans, [p.failure_class for p in found], strict=True))
    scored = [(h, p) for h, p in pairs if "unclear" not in (h, p)]
    majority = majority_baseline(humans)
    return Report(
        labeler=labeler,
        label_file=label_file,
        items=len(items),
        labels=dict(Counter(humans)),
        frozen_version=FROZEN_VERSION,
        triager=score(pairs),
        classes=class_scores(scored),
        rules_alone=score(list(zip(humans, rules_alone(rule_verdicts), strict=True))),
        rules=evaluate_rules(list(zip(labels, rule_verdicts, strict=True))),
        majority_class=majority[0],
        majority=score(list(zip(humans, majority, strict=True))),
        self_agreement=None,
        judge_outcomes=dict(Counter(r.outcome for r in judge_results)),
        judge_dollars=judge_dollars(judge_results),
        disagreements=[
            Disagreement(
                trajectory_id=item.trajectory_id,
                instance_id=item.instance_id,
                labeled=label.failure_class,
                note=label.note,
                predicted=prediction.failure_class,
                source=prediction.source,
                evidence=prediction.evidence,
                confidence=prediction.confidence,
            )
            for item, label, prediction in zip(items, labels, found, strict=True)
            if "unclear" not in (label.failure_class, prediction.failure_class)
            and label.failure_class != prediction.failure_class
        ],
    )


def describe(name: str, result: KappaScore) -> str:
    if result.kappa is None:
        return f"{name}: no scorable items"
    return (
        f"{name}: kappa {result.kappa:.2f} [{result.low:.2f}, {result.high:.2f}] on "
        f"{result.scored} items, agreement {result.agreement:.0%}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the frozen triager on the test labels.")
    parser.add_argument("--labels", type=Path, default=LABELS_PATH, help="the test label file")
    parser.add_argument("--labeler", default=LABELER, help="who wrote the labels")
    args = parser.parse_args()
    try:
        labeled = load_labeled_items(SAMPLE_PATH, args.labels, "test")
    except (FileNotFoundError, ValueError) as error:
        sys.exit(f"{error}\nThe triager runs on the test items only once every one is labeled.")
    items = [item for item, _ in labeled]
    labels = [label for _, label in labeled]
    ran = run_triager(CachedClient(TinkerTransport()), items)
    if ran is None:
        sys.exit("Batch declined; nothing written.")
    report = evaluate(items, labels, *ran, labeler=args.labeler, label_file=str(args.labels))
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(report.model_dump_json(indent=1) + "\n")
    rules = report.rules
    precision = rules.precision
    print(f"labels: {report.label_file}, by {report.labeler}")
    print(describe("triager", report.triager))
    print(describe("rules alone", report.rules_alone))
    print(
        f"rules fired on {rules.coverage.successes} of {rules.coverage.n} items "
        f"({rules.coverage.rate:.0%}); precision on those: "
        + ("none fired" if precision is None else f"{precision.successes} of {precision.n}")
    )
    print(describe(f"always {report.majority_class}", report.majority))
    print(
        f"unclear: labels {report.triager.human_unclear}, triager {report.triager.triager_unclear}"
    )
    print(f"{len(report.disagreements)} disagreements; wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
