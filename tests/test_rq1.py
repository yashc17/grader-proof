from pathlib import Path

import pytest

from grader_proof.labeling import Label, SampleItem, read_labels, read_sample
from grader_proof.rq1 import Rq1, render_markdown, summarize, write_csv
from grader_proof.stats import wilson_interval

FIXTURES = Path(__file__).parent / "fixtures" / "rq1"


@pytest.fixture
def rq1() -> Rq1:
    return summarize(read_labels(FIXTURES / "labels.jsonl"), read_sample(FIXTURES / "sample.jsonl"))


def test_counts_labeled_items_self_checks_and_false_positives(rq1: Rq1):
    """fake-7 passed its self-check but has no label yet, so it is not counted."""
    assert (rq1.labeled, rq1.with_self_check, rq1.false_positives) == (6, 5, 4)


def test_counts_every_reason_in_codebook_order_including_zeros(rq1: Rq1):
    assert [(r.reason, r.count) for r in rq1.rows] == [
        ("too_weak", 2),
        ("wrong_target", 1),
        ("mirrors_patch", 1),
        ("other", 0),
    ]


def test_shares_are_over_false_positives_with_wilson_intervals(rq1: Rq1):
    too_weak = rq1.rows[0]
    assert too_weak.share == 0.5
    assert (too_weak.low, too_weak.high) == wilson_interval(2, 4)


def test_examples_are_up_to_three_notes_per_reason_by_trajectory_id(rq1: Rq1):
    assert [label.trajectory_id for label in rq1.examples["too_weak"]] == ["fake-1", "fake-4"]
    assert rq1.examples["other"] == []


def sample_item(trajectory_id: str, self_check_passed: bool | None) -> SampleItem:
    return SampleItem(
        trajectory_id=trajectory_id,
        instance_id=f"org__{trajectory_id}",
        self_check_passed=self_check_passed,
        split="test",
    )


def label(trajectory_id: str, reason: str | None) -> Label:
    return Label.model_validate(
        {
            "trajectory_id": trajectory_id,
            "failure_class": "model_failure",
            "note": "n",
            "fooled_reason": reason,
        }
    )


@pytest.mark.parametrize(
    ("labels", "message"),
    [
        ([label("t1", None)], "t1: a self-check false positive needs a fooled_reason"),
        ([label("t2", "too_weak")], "t2: only self-check false positives take a fooled_reason"),
        ([label("t9", None)], "t9: not in the sample"),
    ],
)
def test_rejects_labels_that_break_the_fooled_reason_rule(labels: list[Label], message: str):
    sample = [sample_item("t1", True), sample_item("t2", False)]
    with pytest.raises(ValueError, match=message):
        summarize(labels, sample)


def test_rejects_an_empty_label_file():
    with pytest.raises(ValueError, match="no labels"):
        summarize([], [sample_item("t1", True)])


def test_write_csv_has_one_line_per_reason(rq1: Rq1, tmp_path: Path):
    path = tmp_path / "rq1.csv"
    write_csv(rq1, path)
    lines = path.read_text().splitlines()
    assert lines[0] == "fooled_reason,count,false_positives,share,share_low,share_high"
    assert lines[1].startswith("too_weak,2,4,0.5,")
    assert len(lines) == 5


def test_render_markdown_shows_counts_and_examples(rq1: Rq1):
    table = render_markdown(rq1, source=Path("labels/x.jsonl"))
    assert "| too_weak | the self-check does not exercise" in table
    assert "| 2 | 50% [" in table
    assert "- fake-1: self-check only calls the happy path" in table
    assert "labels/x.jsonl" in table


def test_render_markdown_says_why_open_question_6_is_not_answered(rq1: Rq1):
    table = render_markdown(rq1, source=Path("labels/x.jsonl"))
    assert "## Broke a PASS_TO_PASS test or missed a FAIL_TO_PASS test?" in table
    assert "`resolved`, `gen_tests_correct` and `pred_passes_gen_tests`" in table
