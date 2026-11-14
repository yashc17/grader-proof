"""The labeling sample and the hand-label file: drawing, models and JSONL reading and writing.

Labels belong to the maintainer. This module only validates and appends what the CLI collects.
"""

import random
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, field_validator

SAMPLE_PATH = Path("labels/sample.jsonl")
LABELS_PATH = Path("labels/human.jsonl")
SAMPLE_SEED = 0
SAMPLE_SIZE = 100
DEV_SIZE = 30

# Failure classes in precedence order (ADR 0003): when more than one fits, the first wins.
FailureClass = Literal[
    "env_broken", "task_underspecified", "upstream_tests_wrong", "model_failure", "unclear"
]
FooledReason = Literal["too_weak", "wrong_target", "mirrors_patch", "other"]
Split = Literal["dev", "test"]

FAILURE_CLASSES: dict[str, str] = {
    "env_broken": "the environment stopped the agent before code quality mattered",
    "task_underspecified": "the issue does not say what the upstream tests check",
    "upstream_tests_wrong": "the tests check something other than the issue",
    "model_failure": "the task was fair and the patch is wrong, incomplete or missing",
    "unclear": "not enough evidence",
}
FOOLED_REASONS: dict[str, str] = {
    "too_weak": "the self-check does not exercise the behavior the issue describes",
    "wrong_target": "the self-check tests something other than the issue",
    "mirrors_patch": "the self-check asserts what the patch does, not what is required",
    "other": "none of the above; say why in the note",
}
assert tuple(FAILURE_CLASSES) == get_args(FailureClass)
assert tuple(FOOLED_REASONS) == get_args(FooledReason)


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Candidate(Frozen):
    """An unresolved trajectory that can be drawn."""

    trajectory_id: str
    instance_id: str
    self_check_passed: bool | None


class SampleItem(Candidate):
    split: Split


class Label(Frozen):
    trajectory_id: str
    failure_class: FailureClass
    note: str
    fooled_reason: FooledReason | None = None

    @field_validator("note")
    @classmethod
    def note_is_one_line(cls, note: str) -> str:
        note = note.strip()
        if not note or "\n" in note:
            raise ValueError("note must be one non-empty line")
        return note


def draw_sample(
    candidates: Iterable[Candidate], seed: int = SAMPLE_SEED, size: int = SAMPLE_SIZE
) -> list[SampleItem]:
    """Draws `size` trajectories from distinct instances, then splits them at random."""
    pool = sorted(candidates, key=lambda c: c.trajectory_id)
    rng = random.Random(seed)
    rng.shuffle(pool)
    one_per_instance = list({c.instance_id: c for c in reversed(pool)}.values())[::-1]
    if len(one_per_instance) < size:
        raise ValueError(f"only {len(one_per_instance)} instances, need {size}")
    drawn = one_per_instance[:size]
    return [
        SampleItem(**c.model_dump(), split="dev" if i < DEV_SIZE else "test")
        for i, c in enumerate(drawn)
    ]


def write_sample(path: Path, sample: Sequence[SampleItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(item.model_dump_json() + "\n" for item in sample))


def read_sample(path: Path) -> list[SampleItem]:
    return [SampleItem.model_validate_json(line) for line in path.read_text().splitlines()]


def read_labels(path: Path) -> list[Label]:
    if not path.exists():
        return []
    return [Label.model_validate_json(line) for line in path.read_text().splitlines()]


def append_label(path: Path, label: Label) -> None:
    if any(old.trajectory_id == label.trajectory_id for old in read_labels(path)):
        raise ValueError(f"{label.trajectory_id} is already labeled")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as file:
        file.write(label.model_dump_json() + "\n")


def unlabeled(
    sample: Sequence[SampleItem], labels: Sequence[Label], split: Split | Literal["all"]
) -> list[SampleItem]:
    done = {label.trajectory_id for label in labels}
    return [
        item for item in sample if item.trajectory_id not in done and split in ("all", item.split)
    ]


def check_fooled_reason(label: Label, item: SampleItem) -> None:
    """A fooled_reason is needed for self-check false positives and for nothing else."""
    if item.self_check_passed and label.fooled_reason is None:
        raise ValueError("a self-check false positive needs a fooled_reason")
    if not item.self_check_passed and label.fooled_reason is not None:
        raise ValueError("only self-check false positives take a fooled_reason")
