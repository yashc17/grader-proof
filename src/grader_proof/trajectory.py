"""Parses a trajectory row and condenses it into a short view for labeling and the LLM judge.

The labeling tool and the judge both read `CondensedTrajectory.text`, so a human and the judge
see the same evidence. The view leaves out `resolved` and the self-check columns on purpose.
"""

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

# Roughly 4 characters per token for English text and code. It needs no model call and errs a
# little low on code, so the real count can be somewhat higher than the one reported here.
CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS = 4000

MAX_COMMAND_CHARS = 200
MAX_ERROR_CHARS = 200
MAX_OBSERVATION_CHARS = 600
LAST_OBSERVATIONS = 3
MAX_LISTED_FILES = 20
SECTION_SHARES = {"commands": 0.4, "errors": 0.25, "observations": 0.35}

TOOL_CALL_AS_TEXT = ("<tool_call>", "<function=", "<parameter=")
EXIT_CODE = re.compile(r"\[The command completed with exit code (\d+)\.\]")
ERROR_LINE = re.compile(r"\b\w*(Error|Exception)\b")
NOISE_LINE = re.compile(r"^\[(Current working directory|Python interpreter|Command finished)")
DIFF_HEADER = re.compile(r"^diff --git a/.+ b/(.+)$")
BASH, EDITOR, FINISH = "execute_bash", "str_replace_editor", "finish"
NOT_COMMANDS = {"think", "task_tracker"}


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ToolCall(Frozen):
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
    parse_error: str | None = None

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "ToolCall":
        function = raw["function"]
        text = function["arguments"] or ""
        arguments: dict[str, Any] = {}
        error = None
        try:
            parsed: Any = json.loads(text)
            if isinstance(parsed, dict):
                arguments = cast(dict[str, Any], parsed)
            else:
                error = "arguments are not a JSON object"
        except json.JSONDecodeError as e:
            error = str(e)
        return cls(
            id=raw["id"] or "",
            name=function["name"],
            arguments=arguments,
            raw_arguments=text,
            parse_error=error,
        )


class Message(Frozen):
    role: str
    content: str
    tool_calls: tuple[ToolCall, ...]
    # Set on tool messages: the id of the call this message answers.
    tool_call_id: str | None = None


class Trajectory(Frozen):
    """One recorded agent attempt at one instance."""

    trajectory_id: str
    instance_id: str
    repo: str
    exit_status: str
    model_patch: str
    messages: tuple[Message, ...]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Trajectory":
        messages = tuple(
            Message(
                role=raw["role"],
                content=raw["content"] or "",
                tool_calls=tuple(ToolCall.from_raw(c) for c in raw["tool_calls"] or ()),
                tool_call_id=raw.get("tool_call_id"),
            )
            for raw in row["trajectory"]
        )
        return cls(
            trajectory_id=row["trajectory_id"],
            instance_id=row["instance_id"],
            repo=row["repo"],
            exit_status=row["exit_status"],
            model_patch=row["model_patch"] or "",
            messages=messages,
        )


class PatchSummary(Frozen):
    files: tuple[str, ...]
    test_files: tuple[str, ...]
    added: int
    removed: int


class CondensedTrajectory(Frozen):
    """The evidence fields hold everything found; `text` is the version cut to the budget."""

    trajectory_id: str
    instance_id: str
    exit_status: str
    turns: int
    commands: tuple[str, ...]
    errors: tuple[str, ...]
    last_observations: tuple[str, ...]
    patch: PatchSummary
    text: str


def count_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def is_test_file(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return (
        any(part in ("test", "tests") for part in parts[:-1])
        or name.startswith("test_")
        or name.endswith(("_test.py", "_tests.py"))
        or name == "conftest.py"
    )


def summarize_patch(patch: str) -> PatchSummary:
    files: list[str] = []
    added = removed = 0
    for line in patch.splitlines():
        if header := DIFF_HEADER.match(line):
            files.append(header.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return PatchSummary(
        files=tuple(files),
        test_files=tuple(f for f in files if is_test_file(f)),
        added=added,
        removed=removed,
    )


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def one_line(text: str) -> str:
    return " ".join(text.split())


def describe_call(call: ToolCall) -> str | None:
    """The call as one line of text; unparsable arguments are shown raw."""
    if call.name in NOT_COMMANDS:
        return None
    if call.parse_error:
        return clip(
            f"[unparsable {call.name} arguments] {one_line(call.raw_arguments)}", MAX_COMMAND_CHARS
        )
    arguments = call.arguments
    if call.name == BASH and isinstance(arguments.get("command"), str):
        text = arguments["command"]
    elif call.name == EDITOR:
        text = f"{arguments.get('command', '?')} {arguments.get('path', '?')}"
    elif call.name == FINISH:
        text = FINISH
    else:
        text = f"{call.name} {json.dumps(arguments)}"
    return clip(one_line(text), MAX_COMMAND_CHARS)


def observation_error(content: str) -> str | None:
    """The most telling line of a failed tool observation, or None when it did not fail."""
    exit_code = EXIT_CODE.search(content)
    failed_command = exit_code is not None and exit_code.group(1) != "0"
    failed_editor = content.startswith("ERROR:")
    if not (failed_command or failed_editor):
        return None
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if failed_editor:
        lines = lines[1:] or lines
    body = [line for line in lines if not line.startswith("[") and not NOISE_LINE.match(line)]
    if not body and exit_code is not None:
        return f"exit code {exit_code.group(1)}, no output"
    named = [line for line in body if ERROR_LINE.search(line)]
    return clip((named or body or lines)[-1 if failed_command else 0], MAX_ERROR_CHARS)


def clean_observation(content: str) -> str:
    return "\n".join(line for line in content.splitlines() if not NOISE_LINE.match(line)).strip()


def extract_evidence(trajectory: Trajectory) -> tuple[list[str], list[str], list[str]]:
    commands: list[str] = []
    errors: list[str] = []
    observations: list[str] = []
    for index, message in enumerate(trajectory.messages):
        if message.role == "assistant":
            for call in message.tool_calls:
                if (command := describe_call(call)) is not None:
                    commands.append(command)
                if call.parse_error:
                    errors.append(
                        f"#{index}: unparsable arguments for {call.name}: "
                        f"{clip(one_line(call.raw_arguments), MAX_ERROR_CHARS)}"
                    )
            if not message.tool_calls and any(m in message.content for m in TOOL_CALL_AS_TEXT):
                snippet = one_line(message.content[message.content.index("<") :])
                errors.append(
                    f"#{index}: tool call written as text, not executed: "
                    f"{clip(snippet, MAX_ERROR_CHARS)}"
                )
        elif message.role == "tool":
            observations.append(clean_observation(message.content))
            if (error := observation_error(message.content)) is not None:
                errors.append(f"#{index}: {error}")
    return commands, errors, observations


def fit(lines: Sequence[str], budget_tokens: int) -> list[str]:
    """Keeps the first and last lines that fit the budget and marks the cut in the middle."""
    if sum(count_tokens(line) + 1 for line in lines) <= budget_tokens:
        return list(lines)
    head: list[str] = []
    tail: list[str] = []
    used = count_tokens("... 999999 omitted ...") + 1
    for take_head, line in zip_ends(lines):
        cost = count_tokens(line) + 1
        if used + cost > budget_tokens:
            break
        used += cost
        (head if take_head else tail).append(line)
    omitted = len(lines) - len(head) - len(tail)
    return [*head, f"... {omitted} omitted ...", *reversed(tail)]


def zip_ends(lines: Sequence[str]):
    """Yields (is_from_start, line) alternating from the start and the end of `lines`."""
    low, high = 0, len(lines) - 1
    while low <= high:
        yield True, lines[low]
        low += 1
        if low <= high:
            yield False, lines[high]
            high -= 1


def render(
    trajectory: Trajectory,
    patch: PatchSummary,
    commands: Sequence[str],
    errors: Sequence[str],
    observations: Sequence[str],
    max_tokens: int,
) -> str:
    listed = patch.files[:MAX_LISTED_FILES]
    more = len(patch.files) - len(listed)
    header = [
        f"instance: {trajectory.instance_id}",
        f"trajectory: {trajectory.trajectory_id}",
        f"exit_status: {trajectory.exit_status}",
        f"turns: {sum(m.role == 'assistant' for m in trajectory.messages)}",
        "",
        f"## Patch: {len(patch.files)} files, +{patch.added} -{patch.removed}",
        *(f"{f}{'  (test file)' if f in patch.test_files else ''}" for f in listed),
        *([f"... {more} more files"] if more else []),
    ]
    body_tokens = max(max_tokens - count_tokens("\n".join(header)) - 20, 0)
    share = {name: int(body_tokens * fraction) for name, fraction in SECTION_SHARES.items()}
    last = [clip_tail(o, MAX_OBSERVATION_CHARS) for o in observations[-LAST_OBSERVATIONS:]]
    sections = [
        ("## Commands run", fit(commands, share["commands"])),
        ("## Errors seen", fit(errors, share["errors"]) or ["none"]),
        ("## Last observations", fit(last, share["observations"])),
    ]
    text = "\n".join(header)
    for title, lines in sections:
        text += "\n\n" + title + "\n" + "\n".join(lines)
    return text[: max_tokens * CHARS_PER_TOKEN]


def clip_tail(text: str, limit: int) -> str:
    """Keeps the end of the text, where command output usually says what happened."""
    return text if len(text) <= limit else "..." + text[-(limit - 3) :]


def condense(trajectory: Trajectory, max_tokens: int = DEFAULT_MAX_TOKENS) -> CondensedTrajectory:
    commands, errors, observations = extract_evidence(trajectory)
    patch = summarize_patch(trajectory.model_patch)
    last = tuple(clip_tail(o, MAX_OBSERVATION_CHARS) for o in observations[-LAST_OBSERVATIONS:])
    return CondensedTrajectory(
        trajectory_id=trajectory.trajectory_id,
        instance_id=trajectory.instance_id,
        exit_status=trajectory.exit_status,
        turns=sum(m.role == "assistant" for m in trajectory.messages),
        commands=tuple(commands),
        errors=tuple(errors),
        last_observations=last,
        patch=patch,
        text=render(trajectory, patch, commands, errors, observations, max_tokens),
    )
