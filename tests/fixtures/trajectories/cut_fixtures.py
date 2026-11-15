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

# fixture name -> (trajectory_id, message index ranges kept in order, keep_tail)
# keep_tail cuts tool observations from the middle instead of the end. The triage rules read
# the exit code and the error, which are at the end of an observation.
FIXTURES = {
    "normal": ("chatcmpl-c33f1601bba35694576802a0abf4c6f9", [(0, 6), (111, 127)], False),
    "turn_limit": ("chatcmpl-e8b25f7cae5752d91fe74bc287ceeb4a", [(0, 6), (185, 201)], False),
    "malformed_tool_call": ("chatcmpl-386ccb65c6811952b58fde415528875b", [(0, 6), (24, 40)], False),
    "install_failed": (
        "chatcmpl-e4ed5a429bff8c829d9404b29408ea97",
        [(0, 6), (23, 32), (57, 64)],
        True,
    ),
    "no_network": ("chatcmpl-f414c5b4f5a4d7ed46ecf14a3b8dec9c", [(0, 6), (9, 24)], True),
    "import_error": ("chatcmpl-a7e404e12f732d7c261f7ad4ce481b12", [(0, 6), (23, 52)], True),
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


def clip_middle(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit // 3] + "\n...[cut]...\n" + text[-(limit - limit // 3) :]


def cut_message(message: dict, keep_tail: bool) -> dict:
    cut_text = clip_middle if keep_tail and message["role"] == "tool" else clip
    cut = {**message, "content": cut_text(message["content"], MAX_TEXT)}
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
    ids = [trajectory_id for trajectory_id, _, _ in FIXTURES.values()]
    rows = (
        pl.scan_parquet(DATA_DIR / "trajectories/trajectories.parquet")
        .filter(pl.col("trajectory_id").is_in(ids))
        .drop("tools")
        .collect()
        .iter_rows(named=True)
    )
    by_id = {row["trajectory_id"]: row for row in rows}
    for name, (trajectory_id, ranges, keep_tail) in FIXTURES.items():
        row = by_id[trajectory_id]
        messages = [
            cut_message(row["trajectory"][i], keep_tail) for lo, hi in ranges for i in range(lo, hi)
        ]
        fixture = {**row, "trajectory": messages, "full_message_count": len(row["trajectory"])}
        (OUT / f"{name}.json").write_text(json.dumps(fixture, indent=1) + "\n")


if __name__ == "__main__":
    main()
