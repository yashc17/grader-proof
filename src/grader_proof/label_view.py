"""Writes a local web page for hand-labeling the 30 dev items.

Run with `make label-page`, then open data/label_view/index.html in a browser. The page saves
labels in the browser and exports labels/human.jsonl. It does not label anything itself.
"""

import json
from pathlib import Path
from typing import Any

from grader_proof.label_cli import load_row, load_task
from grader_proof.labeling import (
    FAILURE_CLASSES,
    FOOLED_REASONS,
    SAMPLE_PATH,
    SampleItem,
    read_sample,
)
from grader_proof.trajectory import Trajectory, condense

TEMPLATE_PATH = Path(__file__).with_name("label_view.html")
PAGE_PATH = Path("data/label_view/index.html")
DATA_MARKER = "/*DATA*/"


def item_record(item: SampleItem) -> dict[str, Any]:
    row = load_row(item)
    task = load_task(item.instance_id)
    return {
        "trajectory_id": item.trajectory_id,
        "instance_id": item.instance_id,
        "self_check_passed": item.self_check_passed,
        "self_check_separates_gold": row["gen_tests_correct"],
        "issue": task["problem_statement"].strip(),
        "fail_to_pass": list(task["FAIL_TO_PASS"]),
        "trajectory": condense(Trajectory.from_row(row)).text,
        "agent_patch": row["model_patch"] or "",
        "gold_patch": task["patch"],
    }


def embed(data: dict[str, Any]) -> str:
    # "</" is escaped so the JSON cannot close the script tag early.
    return json.dumps(data).replace("</", "<\\/")


def main() -> None:
    dev_items = [item for item in read_sample(SAMPLE_PATH) if item.split == "dev"]
    records = [item_record(item) for item in dev_items]
    data = {
        "items": records,
        "failure_classes": FAILURE_CLASSES,
        "fooled_reasons": FOOLED_REASONS,
    }
    html = TEMPLATE_PATH.read_text().replace(DATA_MARKER, embed(data))
    PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAGE_PATH.write_text(html)
    print(f"wrote {len(records)} dev items to {PAGE_PATH}; open it in a browser")


if __name__ == "__main__":
    main()
