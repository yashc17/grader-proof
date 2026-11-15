from pathlib import Path

import pytest

from grader_proof.judge_eval import score
from grader_proof.label_agreement import AgreementReport, compare, render_markdown
from grader_proof.labeling import Label, SampleItem, read_labels, read_sample
from grader_proof.stats import wilson_interval

FIXTURES = Path(__file__).parent / "fixtures" / "agreement"


@pytest.fixture
def report() -> AgreementReport:
    return compare(
        read_labels(FIXTURES / "a.jsonl"),
        read_labels(FIXTURES / "b.jsonl"),
        read_sample(FIXTURES / "sample.jsonl"),
    )


def test_compares_only_the_ids_in_both_files(report: AgreementReport):
    """A has t1 and B has t8 alone; t2 to t7 are in both."""
    assert (report.shared, report.only_in_a, report.only_in_b) == (6, 1, 1)


def test_failure_class_agreement_leaves_unclear_out_and_counts_it(report: AgreementReport):
    """t6 is unclear for B, so 5 items are scored and 3 of them agree (ADR 0003)."""
    fc = report.failure_class
    assert (fc.items, fc.scored, fc.human_unclear, fc.triager_unclear) == (6, 5, 0, 1)
    assert fc.agreement == 0.6
    assert report.agreement_interval == wilson_interval(3, 5)


def test_failure_class_kappa_matches_the_shared_scorer(report: AgreementReport):
    pairs = [
        ("model_failure", "model_failure"),
        ("env_broken", "env_broken"),
        ("model_failure", "task_underspecified"),
        ("task_underspecified", "task_underspecified"),
        ("model_failure", "unclear"),
        ("upstream_tests_wrong", "model_failure"),
    ]
    assert report.failure_class == score(pairs)
    assert report.failure_class.low is not None


def test_lists_every_disagreeing_class_pair(report: AgreementReport):
    assert report.disagreements == {
        "model_failure -> task_underspecified": 1,
        "model_failure -> unclear": 1,
        "upstream_tests_wrong -> model_failure": 1,
    }


def test_fooled_reason_agreement_on_items_where_both_gave_one(report: AgreementReport):
    """Both: t2 agree, t4 differ, t7 agree. Only A: t5. Only B: t6."""
    reasons = report.fooled_reason
    assert reasons.both == score(
        [("too_weak", "too_weak"), ("mirrors_patch", "too_weak"), ("too_weak", "too_weak")]
    )
    assert reasons.both.agreement == pytest.approx(2 / 3)
    assert (reasons.only_a, reasons.only_b) == (1, 1)


def label(trajectory_id: str) -> Label:
    return Label(trajectory_id=trajectory_id, failure_class="model_failure", note="n")


def sample_item(trajectory_id: str) -> SampleItem:
    return SampleItem(
        trajectory_id=trajectory_id,
        instance_id=f"org__{trajectory_id}",
        self_check_passed=False,
        split="dev",
    )


def test_stops_when_a_file_names_an_id_outside_the_sample():
    with pytest.raises(ValueError, match="B: x9 not in the sample"):
        compare([label("t1")], [label("t1"), label("x9")], [sample_item("t1")])


def test_stops_on_a_duplicate_id():
    with pytest.raises(ValueError, match="A: t1 labeled more than once"):
        compare([label("t1"), label("t1")], [label("t1")], [sample_item("t1")])


def test_stops_when_no_id_is_in_both_files():
    with pytest.raises(ValueError, match="no trajectory is labeled in both files"):
        compare([label("t1")], [label("t2")], [sample_item("t1"), sample_item("t2")])


def test_render_markdown_names_both_files_and_shows_the_numbers(report: AgreementReport):
    table = render_markdown(report, Path("labels/a.jsonl"), Path("labels/b.jsonl"))
    assert "A = `labels/a.jsonl`, B = `labels/b.jsonl`" in table
    assert "| Failure class | 5 | 3/5 = 60% [" in table
    assert "| model_failure | unclear | 1 |" in table
    assert "only A gave one: 1, only B gave one: 1" in table
