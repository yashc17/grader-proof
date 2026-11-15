"""Terminal tools for the labeling sample.

`python -m grader_proof.label_cli sample` draws labels/sample.jsonl.
`python -m grader_proof.label_cli label --split dev` labels one trajectory at a time and appends
each label to labels/human.jsonl, so quitting and restarting resumes at the next unlabeled item.
"""

import argparse
import shutil
import textwrap
from itertools import zip_longest
from typing import Any, Literal

import polars as pl
from pydantic import ValidationError

from grader_proof.data_facts import DATA_DIR
from grader_proof.labeling import (
    FAILURE_CLASSES,
    FOOLED_REASONS,
    LABELS_PATH,
    SAMPLE_PATH,
    SAMPLE_SEED,
    Candidate,
    Label,
    SampleItem,
    Split,
    append_label,
    check_fooled_reason,
    draw_sample,
    read_labels,
    read_sample,
    unlabeled,
    write_sample,
)
from grader_proof.trajectory import Trajectory, condense

TRAJECTORIES = DATA_DIR / "trajectories/trajectories.parquet"
SWE_REBENCH = DATA_DIR / "swe-rebench/*.parquet"


def unresolved_candidates() -> list[Candidate]:
    """Every unresolved trajectory in the data."""
    rows = (
        pl.scan_parquet(TRAJECTORIES)
        .filter(pl.col("resolved") == 0)
        .select("trajectory_id", "instance_id", "pred_passes_gen_tests")
        .collect()
        .iter_rows()
    )
    return [
        Candidate(
            trajectory_id=trajectory_id,
            instance_id=instance_id,
            self_check_passed=None if passed is None else passed == 1,
        )
        for trajectory_id, instance_id, passed in rows
    ]


def command_sample(seed: int, force: bool) -> None:
    sample = draw_sample(unresolved_candidates(), seed)
    if SAMPLE_PATH.exists() and not force:
        print(f"{SAMPLE_PATH} already exists; it is left as it is. Use --force to redraw.")
        return
    write_sample(SAMPLE_PATH, sample)
    print(f"wrote {len(sample)} items to {SAMPLE_PATH}; the split is in the file but not shown")


def load_row(item: SampleItem) -> dict[str, Any]:
    return (
        pl.scan_parquet(TRAJECTORIES)
        .filter(pl.col("trajectory_id") == item.trajectory_id)
        .collect()
        .row(0, named=True)
    )


def load_task(instance_id: str) -> dict[str, Any]:
    return (
        pl.scan_parquet(SWE_REBENCH)
        .filter(pl.col("instance_id") == instance_id)
        .select("problem_statement", "patch", "FAIL_TO_PASS")
        .collect()
        .row(0, named=True)
    )


def side_by_side(left_title: str, left: str, right_title: str, right: str, width: int) -> str:
    half = (width - 3) // 2

    def cut(text: str) -> list[str]:
        return [part for line in text.splitlines() for part in textwrap.wrap(line, half) or [""]]

    rows = [(left_title, right_title), ("-" * half, "-" * half)]
    rows += zip_longest(cut(left), cut(right), fillvalue="")
    return "\n".join(f"{a:<{half}} | {b}" for a, b in rows)


def show(item: SampleItem, position: str) -> None:
    width = shutil.get_terminal_size().columns
    row = load_row(item)
    task = load_task(item.instance_id)
    condensed = condense(Trajectory.from_row(row))
    rule = "=" * width
    print(f"\n{rule}\n{position}   {item.instance_id}\n{rule}")
    print("\n## Issue\n" + task["problem_statement"].strip())
    print("\n## FAIL_TO_PASS\n" + "\n".join(task["FAIL_TO_PASS"]))
    print(
        f"\n## Self-check flags\n"
        f"agent's patch passes its own self-check: {row['pred_passes_gen_tests']}\n"
        f"self-check separates original code from gold patch: {row['gen_tests_correct']}"
    )
    print("\n## Trajectory\n" + condensed.text)
    print(
        "\n## Patches\n"
        + side_by_side(
            "AGENT PATCH", row["model_patch"] or "(empty)", "GOLD PATCH", task["patch"], width
        )
    )


def choose(prompt: str, options: dict[str, str]) -> str | None:
    """Returns the chosen key, or None when the labeler quits."""
    names = list(options)
    for number, name in enumerate(names, 1):
        print(f"  {number}. {name}: {options[name]}")
    while True:
        answer = input(f"{prompt} [1-{len(names)}, q to quit]: ").strip().lower()
        if answer == "q":
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]


def ask_label(item: SampleItem) -> Label | None:
    failure_class = choose("failure class", FAILURE_CLASSES)
    if failure_class is None:
        return None
    fooled_reason = None
    if item.self_check_passed:
        print("\nThe agent's patch passed its own self-check but failed upstream.")
        fooled_reason = choose("why was the self-check fooled", FOOLED_REASONS)
        if fooled_reason is None:
            return None
    while True:
        note = input("one-line note: ")
        try:
            return Label.model_validate(
                {
                    "trajectory_id": item.trajectory_id,
                    "failure_class": failure_class,
                    "note": note,
                    "fooled_reason": fooled_reason,
                }
            )
        except ValidationError:
            print("The note must be one non-empty line.")


def command_label(split: Split | Literal["all"]) -> None:
    sample = read_sample(SAMPLE_PATH)
    total = sum(split in ("all", item.split) for item in sample)
    while todo := unlabeled(sample, read_labels(LABELS_PATH), split):
        item = todo[0]
        show(item, f"{total - len(todo) + 1} of {total} ({split})")
        label = ask_label(item)
        if label is None:
            print("Quit. Run the same command to resume.")
            return
        check_fooled_reason(label, item)
        append_label(LABELS_PATH, label)
    print(f"All {total} {split} items are labeled.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw and label the labeling sample.")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample", help="draw labels/sample.jsonl")
    sample.add_argument("--seed", type=int, default=SAMPLE_SEED)
    sample.add_argument("--force", action="store_true", help="overwrite an existing sample")
    label = commands.add_parser("label", help="label the next unlabeled trajectory")
    label.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    args = parser.parse_args()
    if args.command == "sample":
        command_sample(args.seed, args.force)
    else:
        command_label(args.split)


if __name__ == "__main__":
    main()
