from pathlib import Path

import pytest

from grader_proof.judge import JudgeResult, JudgeVerdict
from grader_proof.label_agreement import compare
from grader_proof.labeling import Candidate, FailureClass, Label, SampleItem, Split, write_sample
from grader_proof.rules_eval import load_labeled_items
from grader_proof.triage_eval import (
    ABSTAIN,
    class_scores,
    evaluate,
    load_relabels,
    majority_baseline,
    predictions,
    rules_alone,
)
from grader_proof.triage_rules import Verdict

MF: FailureClass = "model_failure"
TU: FailureClass = "task_underspecified"
EB: FailureClass = "env_broken"
UN: FailureClass = "unclear"


def item(trajectory_id: str, split: Split = "test") -> SampleItem:
    return SampleItem(
        trajectory_id=trajectory_id,
        instance_id=f"i-{trajectory_id}",
        self_check_passed=None,
        split=split,
    )


def label(trajectory_id: str, failure_class: FailureClass) -> Label:
    return Label(
        trajectory_id=trajectory_id, failure_class=failure_class, note=f"note {trajectory_id}"
    )


def rule(failure_class: FailureClass) -> Verdict:
    return Verdict(rule="turn_limit", failure_class=failure_class, evidence="stopped at turn 100")


def judged(failure_class: FailureClass, evidence: str = "patch misses the case") -> JudgeResult:
    return JudgeResult(
        verdict=JudgeVerdict(evidence=evidence, failure_class=failure_class, confidence=0.7),
        outcome="parsed",
        prompt_tokens=10,
        completion_tokens=5,
    )


def test_load_labeled_items_reads_the_test_split_only(tmp_path):
    sample = tmp_path / "sample.jsonl"
    write_sample(sample, [item("d1", "dev"), item("t1"), item("t2")])
    labels = tmp_path / "human.jsonl"
    labels.write_text(
        "".join(
            lab.model_dump_json() + "\n"
            for lab in (label("d1", MF), label("t1", TU), label("t2", UN))
        )
    )
    loaded = load_labeled_items(sample, labels, "test")
    assert [(i.trajectory_id, lab.failure_class) for i, lab in loaded] == [("t1", TU), ("t2", UN)]


def test_triage_eval_refuses_to_run_before_every_test_item_is_labeled(tmp_path):
    sample = tmp_path / "sample.jsonl"
    write_sample(sample, [item("t1"), item("t2")])
    labels = tmp_path / "human.jsonl"
    labels.write_text(label("t1", MF).model_dump_json() + "\n")
    with pytest.raises(ValueError, match="t2"):
        load_labeled_items(sample, labels, "test")


def test_predictions_take_the_rule_where_one_fired_and_the_judge_elsewhere_in_order():
    found = predictions([rule(EB), None, None], [judged(MF, "a"), judged(TU, "b")])
    assert [(p.failure_class, p.source, p.evidence) for p in found] == [
        (EB, "rule:turn_limit", "stopped at turn 100"),
        (MF, "judge", "a"),
        (TU, "judge", "b"),
    ]
    assert found[0].confidence is None
    assert found[1].confidence == 0.7


def test_predictions_need_one_judge_result_per_abstention():
    with pytest.raises(ValueError, match="abstention"):
        predictions([None, None], [judged(MF)])


def test_rules_alone_marks_abstentions_as_their_own_class():
    assert rules_alone([rule(EB), None]) == [EB, ABSTAIN]


def test_majority_baseline_predicts_the_most_common_human_class_other_than_unclear():
    assert majority_baseline([UN, UN, UN, MF, MF, TU]) == [MF] * 6


def test_class_scores_count_precision_and_recall_per_class():
    pairs = [(MF, MF), (MF, MF), (MF, TU), (TU, TU), (TU, MF), (EB, MF)]
    scores = class_scores(pairs)
    assert (scores[MF].true_positives, scores[MF].predicted, scores[MF].actual) == (2, 4, 3)
    assert scores[MF].precision == pytest.approx(0.5)
    assert scores[MF].recall == pytest.approx(2 / 3)
    assert scores[EB].precision is None  # never predicted
    assert scores[EB].recall == 0


def test_evaluate_scores_the_triager_and_both_baselines_and_lists_disagreements():
    items = [item(f"t{i}") for i in range(6)]
    labels = [
        label("t0", EB),
        label("t1", MF),
        label("t2", MF),
        label("t3", TU),
        label("t4", MF),
        label("t5", UN),
    ]
    rule_verdicts = [rule(EB), None, None, None, rule(MF), None]
    judge_results = [judged(MF), judged(MF), judged(MF, "wrong"), judged(TU)]
    report = evaluate(
        items, labels, rule_verdicts, judge_results, labeler="Opus", label_file="opus.jsonl"
    )

    assert report.items == 6
    assert (report.labeler, report.label_file) == ("Opus", "opus.jsonl")
    assert report.triager.scored == 5  # t5 is unclear
    assert report.triager.human_unclear == 1
    assert report.majority_class == MF
    assert report.majority.kappa == 0
    assert report.rules_alone.confusion["model_failure -> abstain"] == 2
    # Both rules that fired match the label: coverage 2 of 6, precision 2 of 2.
    assert (report.rules.coverage.successes, report.rules.coverage.n) == (2, 6)
    assert report.rules.precision is not None
    assert (report.rules.precision.successes, report.rules.precision.n) == (2, 2)
    # Only scored items count: t5 (human unclear) is not listed.
    (disagreement,) = report.disagreements
    assert disagreement.trajectory_id == "t3"
    assert (disagreement.labeled, disagreement.predicted) == (TU, MF)
    assert disagreement.note == "note t3"
    assert disagreement.evidence == "wrong"
    assert report.self_agreement is None


def test_evaluate_populates_self_agreement_from_relabels_when_provided():
    items = [item(f"t{i}") for i in range(6)]
    labels = [
        label("t0", EB),
        label("t1", MF),
        label("t2", MF),
        label("t3", TU),
        label("t4", MF),
        label("t5", UN),
    ]
    rule_verdicts = [rule(EB), None, None, None, rule(MF), None]
    judge_results = [judged(MF), judged(MF), judged(MF, "wrong"), judged(TU)]
    relabels = [label("t0", EB), label("t1", MF), label("t2", TU), label("t3", TU), label("t5", MF)]
    report = evaluate(
        items,
        labels,
        rule_verdicts,
        judge_results,
        labeler="Opus",
        label_file="opus.jsonl",
        relabels=relabels,
        sample=items,
    )
    assert report.self_agreement == compare(labels, relabels, items).failure_class
    assert report.self_agreement is not None
    assert (report.self_agreement.items, report.self_agreement.scored) == (5, 4)
    assert report.self_agreement.human_unclear == 1
    assert report.self_agreement.agreement == pytest.approx(3 / 4)
    without_sample = evaluate(
        items,
        labels,
        rule_verdicts,
        judge_results,
        labeler="Opus",
        label_file="opus.jsonl",
        relabels=relabels,
    )
    assert without_sample.self_agreement == report.self_agreement


def test_evaluate_requires_sample_when_relabeling_plain_candidates():
    candidates = [Candidate(trajectory_id="t0", instance_id="i-t0", self_check_passed=None)]
    with pytest.raises(ValueError, match="sample is required"):
        evaluate(
            candidates,
            [label("t0", MF)],
            [rule(MF)],
            [],
            labeler="Opus",
            label_file="opus.jsonl",
            relabels=[label("t0", MF)],
        )


def test_evaluate_leaves_self_agreement_none_when_relabels_are_empty():
    items = [item("t0")]
    labels = [label("t0", MF)]
    report = evaluate(
        items,
        labels,
        [rule(MF)],
        [],
        labeler="Opus",
        label_file="opus.jsonl",
        relabels=[],
        sample=items,
    )
    assert report.self_agreement is None


def test_load_relabels_returns_none_when_missing_or_empty(tmp_path: Path):
    assert load_relabels(None) is None
    assert load_relabels(tmp_path / "missing.jsonl") is None
    assert load_relabels(tmp_path) is None
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert load_relabels(empty) is None

    relabel_file = tmp_path / "relabels.jsonl"
    row = label("t0", MF)
    relabel_file.write_text(row.model_dump_json() + "\n")
    assert load_relabels(relabel_file) == [row]
