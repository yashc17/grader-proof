import json
from pathlib import Path

import pytest

from grader_proof.labeling import FailureClass, Label, SampleItem, Split, write_sample
from grader_proof.rules_eval import evaluate, load_dev_items
from grader_proof.triage_rules import Verdict


def item(trajectory_id: str, split: Split) -> SampleItem:
    return SampleItem(
        trajectory_id=trajectory_id,
        instance_id=f"i-{trajectory_id}",
        self_check_passed=None,
        split=split,
    )


def label(trajectory_id: str, failure_class: FailureClass) -> Label:
    return Label(trajectory_id=trajectory_id, failure_class=failure_class, note="n")


def verdict(failure_class: FailureClass, rule: str = "r") -> Verdict:
    return Verdict(rule=rule, failure_class=failure_class, evidence="e")


def write_files(tmp_path: Path, labels: list[str]) -> tuple[Path, Path]:
    sample = tmp_path / "sample.jsonl"
    write_sample(sample, [item("d1", "dev"), item("d2", "dev"), item("t1", "test")])
    labels_path = tmp_path / "human.jsonl"
    labels_path.write_text("".join(line + "\n" for line in labels))
    return sample, labels_path


def test_load_dev_items_returns_only_dev_items_with_their_labels(tmp_path: Path):
    sample, labels = write_files(
        tmp_path,
        [
            label("d1", "model_failure").model_dump_json(),
            label("d2", "unclear").model_dump_json(),
            label("t1", "env_broken").model_dump_json(),
        ],
    )
    loaded = load_dev_items(sample, labels)
    assert [(i.trajectory_id, lab.failure_class) for i, lab in loaded] == [
        ("d1", "model_failure"),
        ("d2", "unclear"),
    ]


def test_test_labels_are_never_parsed(tmp_path: Path):
    # A test line that is not even a valid label would raise if it were parsed as one.
    broken_test_line = json.dumps({"trajectory_id": "t1", "failure_class": "not a class"})
    sample, labels = write_files(
        tmp_path,
        [
            label("d1", "model_failure").model_dump_json(),
            label("d2", "unclear").model_dump_json(),
            broken_test_line,
        ],
    )
    assert len(load_dev_items(sample, labels)) == 2


def test_missing_dev_label_is_an_error(tmp_path: Path):
    sample, labels = write_files(tmp_path, [label("d1", "model_failure").model_dump_json()])
    with pytest.raises(ValueError, match="d2"):
        load_dev_items(sample, labels)


def test_missing_label_file_says_what_to_do(tmp_path: Path):
    sample, _ = write_files(tmp_path, [])
    with pytest.raises(FileNotFoundError, match=r"human\.jsonl"):
        load_dev_items(sample, tmp_path / "nope" / "human.jsonl")


def test_evaluate_counts_coverage_and_precision():
    pairs = [
        (label("a", "model_failure"), verdict("model_failure", "turn_limit")),
        (label("b", "model_failure"), verdict("model_failure", "turn_limit")),
        (label("c", "unclear"), verdict("model_failure", "turn_limit")),
        (label("d", "model_failure"), None),
    ]
    report = evaluate(pairs)
    assert (report.items, report.fired, report.correct) == (4, 3, 2)
    assert report.coverage.rate == 0.75
    assert report.precision is not None
    assert report.precision.rate == pytest.approx(2 / 3)
    assert report.rules["turn_limit"].fired == 3
    assert report.rules["turn_limit"].correct == 2
    assert report.labels == {"model_failure": 3, "unclear": 1}


def test_evaluate_with_no_firing_rule_has_no_precision():
    report = evaluate([(label("a", "model_failure"), None)])
    assert report.fired == 0
    assert report.precision is None
