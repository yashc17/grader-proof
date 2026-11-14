import pytest

from grader_proof.judge_eval import combine, score
from grader_proof.labeling import FailureClass
from grader_proof.triage_rules import Verdict

MF: FailureClass = "model_failure"
TU: FailureClass = "task_underspecified"
UN: FailureClass = "unclear"


def test_perfect_agreement_scores_kappa_one() -> None:
    result = score([(MF, MF), (TU, TU), (MF, MF), (TU, TU)])
    assert result.kappa == 1
    assert result.scored == 4
    assert result.agreement == 1


def test_unclear_on_either_side_is_left_out_of_kappa_and_counted() -> None:
    result = score([(MF, MF), (TU, TU), (UN, MF), (MF, UN), (UN, UN)])
    assert result.kappa == 1
    assert result.scored == 2
    assert result.human_unclear == 2
    assert result.triager_unclear == 2


def test_kappa_matches_cohens_formula() -> None:
    # observed 3/4; chance (3*2 + 1*2) / 16 = 0.5; kappa (0.75 - 0.5) / 0.5 = 0.5
    result = score([(MF, MF), (MF, MF), (MF, TU), (TU, TU)])
    assert result.kappa == pytest.approx(0.5)
    assert result.agreement == pytest.approx(0.75)


def test_interval_brackets_the_estimate() -> None:
    pairs = [(MF, MF)] * 8 + [(TU, TU)] * 3 + [(MF, TU), (TU, MF)]
    result = score(pairs)
    assert result.kappa is not None
    assert result.low is not None
    assert result.high is not None
    assert result.low <= result.kappa <= result.high


def test_no_scorable_items_gives_no_kappa() -> None:
    result = score([(UN, MF), (MF, UN)])
    assert result.kappa is None
    assert result.low is None
    assert result.scored == 0


def test_confusion_counts_every_pair_including_unclear() -> None:
    result = score([(MF, MF), (MF, TU), (MF, TU), (UN, MF)])
    assert result.confusion == {
        "model_failure -> model_failure": 1,
        "model_failure -> task_underspecified": 2,
        "unclear -> model_failure": 1,
    }


def test_a_rule_verdict_wins_and_the_judge_fills_the_abstentions() -> None:
    rules = [Verdict(rule="turn_limit", failure_class=MF, evidence="e"), None, None]
    assert combine(rules, [TU, UN]) == [MF, TU, UN]


def test_combine_needs_one_judge_class_per_abstention() -> None:
    with pytest.raises(ValueError, match="abstention"):
        combine([None, None], [TU])
