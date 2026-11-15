"""Writes one fact sheet per test item of the labeling sample, to speed up hand labeling (#9).

A sheet states facts from the data and never suggests a label. The test items are the answer key
for the triager's agreement with a human (#14), so a sheet shows no failure class, no fooled
reason, and nothing from the rules or the LLM judge. Everything on it is computed here, without
model calls, from the trajectory row and the SWE-rebench row.

Run with `make fact-sheets`, then open labels/fact_sheets/test/index.html in a browser.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import jinja2
import polars as pl

from grader_proof.label_cli import SWE_REBENCH, TRAJECTORIES
from grader_proof.labeling import SAMPLE_PATH, SampleItem, read_sample
from grader_proof.trajectory import (
    BASH,
    DIFF_HEADER,
    EXIT_CODE,
    FINISH,
    Frozen,
    ToolCall,
    Trajectory,
    clean_observation,
    clip,
    describe_call,
    one_line,
)

TEMPLATE_PATH = Path(__file__).with_name("fact_sheet.html")
OUT_DIR = Path("labels/fact_sheets/test")

# All 6,003 runs in the trajectory data that stopped at a limit name "max iteration: 100".
TURN_LIMIT = 100
LAST_ACTIONS = 3
LAST_LINES = 3
MAX_SUMMARY_LINES = 10
MAX_FINISH_MESSAGE_CHARS = 600
LONG_ISSUE_CHARS = 1500

# A command runs tests if one of its `&&`, `||`, `;` or `|` parts starts a test runner or runs a
# Python file named like a test. Environment assignments and `timeout N` may come first.
COMMAND_PARTS = re.compile(r"&&|\|\||[;|\n]")
TEST_PART = re.compile(
    r"^(?:\w+=\S*\s+)*(?:timeout\s+\d+\s+)?"
    r"(?:(?:pytest|py\.test|tox|nosetests)\b"
    r"|python[\d.]*\s+(?:-\S+\s+)*(?:-m\s+(?:pytest|unittest|nose)\b|\S*test\w*\.py\b))"
)
# Result lines of pytest and unittest: pytest's final `=== 1 failed, 2 passed ===` line and its
# `FAILED test_id` lines, and unittest's `Ran N tests` and `OK` or `FAILED (...)` lines.
SUMMARY_LINE = re.compile(
    r"^=+ .*\b(passed|failed|errors?|skipped|xfailed|xpassed|deselected|no tests ran)\b.* =+$"
    r"|^(FAILED|ERROR)\b"
    r"|^Ran \d+ tests? in "
    r"|^OK\b"
)


class FileDiff(Frozen):
    """One file's section of the agent's patch and of the gold patch; None if a patch skips it."""

    path: str
    agent: str | None
    gold: str | None
    hidden: bool

    @property
    def shared(self) -> bool:
        return self.agent is not None and self.gold is not None


class Action(Frozen):
    """A tool call and the observation it got, or None if the run ended before one came."""

    command: str
    observation: str | None


class AgentTestRun(Frozen):
    command: str
    exit_code: str | None
    summary: tuple[str, ...]
    last_lines: tuple[str, ...]


class Ending(Frozen):
    turns: int
    limit: int
    exit_status: str
    last_actions: tuple[Action, ...]


def split_patch(patch: str) -> dict[str, str]:
    """Each file's section of a `git diff` patch, keyed by its path after the patch."""
    sections: dict[str, str] = {}
    for section in re.split(r"^(?=diff --git )", patch, flags=re.MULTILINE):
        if header := DIFF_HEADER.match(section.split("\n", 1)[0]):
            sections[header.group(1)] = section.rstrip("\n")
    return sections


def is_hidden(path: str) -> bool:
    """Dot folders and files, bytecode caches and build metadata, such as `.hypothesis/`."""
    parts = path.split("/")
    return (
        any(part.startswith(".") or part == "__pycache__" for part in parts)
        or any(part.endswith(".egg-info") for part in parts[:-1])
        or parts[-1].endswith((".pyc", ".pyo"))
    )


def pair_files(agent_patch: str, gold_patch: str) -> list[FileDiff]:
    """Files both patches touch first, then the agent's own, then the gold patch's, then hidden
    files. Alphabetical within each group."""
    agent, gold = split_patch(agent_patch), split_patch(gold_patch)
    files = [
        FileDiff(path=path, agent=agent.get(path), gold=gold.get(path), hidden=is_hidden(path))
        for path in agent | gold
    ]
    return sorted(files, key=lambda f: (f.hidden, not f.shared, f.agent is None, f.path))


def action_command(call: ToolCall) -> str | None:
    """A shell command in full, the finish message clipped, other calls as one line."""
    if call.name == BASH and isinstance(command := call.arguments.get("command"), str):
        return command.strip()
    if call.name == FINISH and isinstance(message := call.arguments.get("message"), str):
        return f"finish: {clip(one_line(message), MAX_FINISH_MESSAGE_CHARS)}"
    return describe_call(call)


def actions(trajectory: Trajectory) -> list[Action]:
    """Every tool call except `think` and `task_tracker`, in order, with its observation."""
    observations = {
        message.tool_call_id: clean_observation(message.content)
        for message in trajectory.messages
        if message.role == "tool" and message.tool_call_id
    }
    return [
        Action(command=command, observation=observations.get(call.id))
        for message in trajectory.messages
        if message.role == "assistant"
        for call in message.tool_calls
        if (command := action_command(call)) is not None
    ]


def is_test_command(command: str) -> bool:
    return any(TEST_PART.match(part.strip()) for part in COMMAND_PARTS.split(command))


def agent_test_runs(found: Sequence[Action]) -> list[AgentTestRun]:
    """The agent's test commands with the result lines of their output, quoted as printed."""
    runs: list[AgentTestRun] = []
    for action in found:
        if not is_test_command(action.command):
            continue
        output = action.observation or ""
        exit_code = EXIT_CODE.search(output)
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        body = [line for line in lines if not EXIT_CODE.fullmatch(line)]
        summary = [line for line in body if SUMMARY_LINE.match(line)]
        runs.append(
            AgentTestRun(
                command=action.command,
                exit_code=exit_code.group(1) if exit_code else None,
                summary=tuple(summary[-MAX_SUMMARY_LINES:]),
                last_lines=() if summary else tuple(body[-LAST_LINES:]),
            )
        )
    return runs


def ending(trajectory: Trajectory, found: Sequence[Action]) -> Ending:
    return Ending(
        turns=sum(message.role == "assistant" for message in trajectory.messages),
        limit=TURN_LIMIT,
        exit_status=trajectory.exit_status,
        last_actions=tuple(found[-LAST_ACTIONS:]),
    )


def diff_lines(text: str) -> list[tuple[str, str]]:
    """Each line of a patch section with its CSS class: added, removed or plain."""

    def kind(line: str) -> str:
        if line.startswith("+") and not line.startswith("+++"):
            return "add"
        if line.startswith("-") and not line.startswith("---"):
            return "del"
        return ""

    return [(kind(line), line) for line in text.splitlines()]


def sheet_name(number: int, instance_id: str) -> str:
    return f"{number:02d}-{instance_id}.html"


def sheet_context(
    number: int, item: SampleItem, row: dict[str, Any], task: dict[str, Any]
) -> dict[str, Any]:
    trajectory = Trajectory.from_row(row)
    found = actions(trajectory)
    issue = task["problem_statement"].replace("\r\n", "\n").strip()
    return {
        "number": number,
        "item": item,
        "repo": row["repo"],
        "issue": issue,
        "issue_is_long": len(issue) > LONG_ISSUE_CHARS,
        "self_check_passed": row["pred_passes_gen_tests"],
        "self_check_separates_gold": row["gen_tests_correct"],
        "fail_to_pass": list(task["FAIL_TO_PASS"]),
        "pass_to_pass": list(task["PASS_TO_PASS"]),
        "files": pair_files(row["model_patch"] or "", task["patch"]),
        "test_runs": agent_test_runs(found),
        "ending": ending(trajectory, found),
    }


def load_rows(items: Sequence[SampleItem]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Trajectory rows by trajectory id and SWE-rebench rows by instance id, one scan each."""
    trajectories = (
        pl.scan_parquet(TRAJECTORIES)
        .filter(pl.col("trajectory_id").is_in([i.trajectory_id for i in items]))
        .drop("tools")
        .collect()
    )
    tasks = (
        pl.scan_parquet(SWE_REBENCH)
        .filter(pl.col("instance_id").is_in([i.instance_id for i in items]))
        .select("instance_id", "problem_statement", "patch", "FAIL_TO_PASS", "PASS_TO_PASS")
        .collect()
    )
    return (
        {row["trajectory_id"]: row for row in trajectories.iter_rows(named=True)},
        {row["instance_id"]: row for row in tasks.iter_rows(named=True)},
    )


def main() -> None:
    items = [item for item in read_sample(SAMPLE_PATH) if item.split == "test"]
    rows, tasks = load_rows(items)
    template = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATE_PATH.parent),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
    ).get_template(TEMPLATE_PATH.name)
    helpers = {"diff_lines": diff_lines, "sheet_name": sheet_name}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheets = [
        sheet_context(n, item, rows[item.trajectory_id], tasks[item.instance_id])
        for n, item in enumerate(items, 1)
    ]
    names = [sheet_name(sheet["number"], sheet["item"].instance_id) for sheet in sheets]
    for index, sheet in enumerate(sheets):
        page = template.render(
            page="sheet",
            sheet=sheet,
            total=len(sheets),
            previous=names[index - 1] if index > 0 else None,
            next=names[index + 1] if index + 1 < len(names) else None,
            **helpers,
        )
        (OUT_DIR / names[index]).write_text(page)
    (OUT_DIR / "index.html").write_text(template.render(page="index", sheets=sheets, **helpers))
    print(f"wrote {len(sheets)} fact sheets and an index to {OUT_DIR}; open index.html")


if __name__ == "__main__":
    main()
