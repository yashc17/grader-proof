import pytest
from pydantic import ValidationError

from grader_proof.labeling import (
    DEV_SIZE,
    SAMPLE_SIZE,
    Candidate,
    Label,
    SampleItem,
    append_label,
    check_fooled_reason,
    draw_sample,
    read_labels,
    read_sample,
    unlabeled,
    write_sample,
)


def candidates(instances: int = 300, per_instance: int = 3) -> list[Candidate]:
    return [
        Candidate(
            trajectory_id=f"t{i}-{j}",
            instance_id=f"inst{i}",
            self_check_passed=(i + j) % 2 == 0,
        )
        for i in range(instances)
        for j in range(per_instance)
    ]


def test_sample_has_100_items_split_30_70():
    sample = draw_sample(candidates(), seed=0)
    assert len(sample) == SAMPLE_SIZE
    assert sum(item.split == "dev" for item in sample) == DEV_SIZE
    assert sum(item.split == "test" for item in sample) == SAMPLE_SIZE - DEV_SIZE


def test_sample_has_at_most_one_item_per_instance():
    sample = draw_sample(candidates(), seed=0)
    assert len({item.instance_id for item in sample}) == len(sample)


def test_same_seed_gives_same_sample_and_other_seed_differs():
    assert draw_sample(candidates(), seed=1) == draw_sample(candidates(), seed=1)
    assert draw_sample(candidates(), seed=1) != draw_sample(candidates(), seed=2)


def test_sample_does_not_depend_on_candidate_order():
    pool = candidates()
    assert draw_sample(pool, seed=3) == draw_sample(pool[::-1], seed=3)


def test_too_few_instances_is_an_error():
    with pytest.raises(ValueError, match="only 5 instances"):
        draw_sample(candidates(instances=5), seed=0)


def test_sample_round_trips_through_jsonl(tmp_path):
    path = tmp_path / "sample.jsonl"
    sample = draw_sample(candidates(), seed=0)
    write_sample(path, sample)
    assert read_sample(path) == sample


def label(trajectory_id: str = "t1", **fields: object) -> Label:
    values: dict[str, object] = {
        "trajectory_id": trajectory_id,
        "failure_class": "model_failure",
        "note": "patch edits the wrong function",
    } | fields
    return Label.model_validate(values)


def test_labels_are_appended_and_read_back(tmp_path):
    path = tmp_path / "human.jsonl"
    assert read_labels(path) == []
    append_label(path, label("a"))
    append_label(path, label("b", failure_class="env_broken", note="no module named foo"))
    assert [item.trajectory_id for item in read_labels(path)] == ["a", "b"]


def test_label_rejects_unknown_class_empty_note_and_multiline_note():
    with pytest.raises(ValidationError):
        label(failure_class="weak_verifier")
    with pytest.raises(ValidationError):
        label(note="  ")
    with pytest.raises(ValidationError):
        label(note="two\nlines")


def test_label_rejects_unknown_fooled_reason():
    with pytest.raises(ValidationError):
        label(fooled_reason="bad luck")


def test_relabeling_the_same_trajectory_is_an_error(tmp_path):
    path = tmp_path / "human.jsonl"
    append_label(path, label("a"))
    with pytest.raises(ValueError, match="already labeled"):
        append_label(path, label("a"))


def test_unlabeled_resumes_at_the_next_item_and_filters_by_split(tmp_path):
    sample = [
        SampleItem(trajectory_id="a", instance_id="i1", split="dev", self_check_passed=None),
        SampleItem(trajectory_id="b", instance_id="i2", split="test", self_check_passed=None),
        SampleItem(trajectory_id="c", instance_id="i3", split="dev", self_check_passed=None),
    ]
    path = tmp_path / "human.jsonl"
    append_label(path, label("a"))
    assert [i.trajectory_id for i in unlabeled(sample, read_labels(path), "dev")] == ["c"]
    assert [i.trajectory_id for i in unlabeled(sample, read_labels(path), "test")] == ["b"]
    assert [i.trajectory_id for i in unlabeled(sample, read_labels(path), "all")] == ["b", "c"]


def item(self_check_passed: bool | None) -> SampleItem:
    return SampleItem(
        trajectory_id="t1", instance_id="i1", split="dev", self_check_passed=self_check_passed
    )


def test_fooled_reason_is_required_exactly_for_self_check_false_positives():
    check_fooled_reason(label(fooled_reason="too_weak"), item(True))
    check_fooled_reason(label(), item(False))
    check_fooled_reason(label(), item(None))
    with pytest.raises(ValueError, match="needs a fooled_reason"):
        check_fooled_reason(label(), item(True))
    with pytest.raises(ValueError, match="only self-check false positives"):
        check_fooled_reason(label(fooled_reason="too_weak"), item(False))
