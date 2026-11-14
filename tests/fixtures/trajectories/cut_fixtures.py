"""Cuts the small fixture trajectories in this directory from the pinned parquet.

Run with `uv run python tests/fixtures/trajectories/cut_fixtures.py` after `make data-facts`.
Each fixture is a real row with its messages cut down; see README.md for what is cut.
"""

import json
from pathlib import Path

import polars as pl

from grader_proof.data_facts import DATA_DIR

OUT = Path(__file__).parent
MAX_TEXT = 500
MAX_ARGUMENT_VALUE = 300

# fixture name -> (trajectory_id, message index ranges kept, in order)
FIXTURES = {
    "normal": ("chatcmpl-c33f1601bba35694576802a0abf4c6f9", [(0, 6), (111, 127)]),
    "turn_limit": ("chatcmpl-e8b25f7cae5752d91fe74bc287ceeb4a", [(0, 6), (185, 201)]),
    "malformed_tool_call": ("chatcmpl-386ccb65c6811952b58fde415528875b", [(0, 6), (24, 40)]),
}


def clip(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + "...[cut]"


def clip_arguments(arguments: str) -> str:
    """Shortens long string values inside the JSON, keeping the structure and validity."""
    parsed = json.loads(arguments)
    return json.dumps(
        {k: clip(v, MAX_ARGUMENT_VALUE) if isinstance(v, str) else v for k, v in parsed.items()}
    )


def cut_message(message: dict) -> dict:
    cut = {**message, "content": clip(message["content"], MAX_TEXT)}
    if message["tool_calls"]:
        cut["tool_calls"] = [
            {
                **call,
                "function": {
                    **call["function"],
                    "arguments": clip_arguments(call["function"]["arguments"]),
                },
            }
            for call in message["tool_calls"]
        ]
    return cut


def main() -> None:
    ids = [trajectory_id for trajectory_id, _ in FIXTURES.values()]
    rows = (
        pl.scan_parquet(DATA_DIR / "trajectories/trajectories.parquet")
        .filter(pl.col("trajectory_id").is_in(ids))
        .drop("tools")
        .collect()
        .iter_rows(named=True)
    )
    by_id = {row["trajectory_id"]: row for row in rows}
    for name, (trajectory_id, ranges) in FIXTURES.items():
        row = by_id[trajectory_id]
        messages = [cut_message(row["trajectory"][i]) for lo, hi in ranges for i in range(lo, hi)]
        fixture = {**row, "trajectory": messages, "full_message_count": len(row["trajectory"])}
        (OUT / f"{name}.json").write_text(json.dumps(fixture, indent=1) + "\n")


if __name__ == "__main__":
    main()
