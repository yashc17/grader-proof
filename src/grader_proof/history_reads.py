"""Counts trajectories whose commands read git history beyond HEAD (issue #56).

SWE-rebench images keep the repository's future history, so an agent can read the fix with
`git log --all`. Run with `make history-reads`. It reads the pinned trajectories in data/
(`make data-facts` downloads them) and writes results/history_reads.json.

A command is a read of future history if it names:
- `all_refs`: every ref, as in `git log --all` or `git for-each-ref`.
- `remote_ref`: a remote branch or the remote itself, as in `git diff origin/main` or `git fetch`.
- `reflog`: the reflog, as in `git reflog` or `HEAD@{2}`.
- `sha`: a commit by hash, as in `git show 1a2b3c4`. Weaker evidence: the hash may be one the agent
  made itself or one from `git log`, and this check cannot tell which commit it names. It is
  counted on its own and left out of `any_read`.

Commands that name a URL, such as `git ls-remote https://github.com/o/r.git`, read another
repository, not the task's history, and do not count.
"""

import json
import re
import shlex
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import polars as pl

from grader_proof.data_facts import DATA_DIR, RESULTS_DIR
from grader_proof.trajectory import BASH, Trajectory

KINDS = ("all_refs", "remote_ref", "reflog", "sha")
STRONG_KINDS = ("all_refs", "remote_ref", "reflog")
MAX_EXAMPLES = 3
BATCH_ROWS = 2000

SEPARATORS = re.compile(r"&&|\|\||[;|\n]")
GIT_SEGMENT = re.compile(r"^(?:\w+=\S*\s+)*git\s+(.*)$", re.DOTALL)
# Options of `git` itself that take a value and come before the subcommand.
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree"}
ALL_REFS_FLAGS = {"--all", "--branches", "--remotes", "--tags"}
ALL_REFS_COMMANDS = {"for-each-ref", "show-ref"}
# Commands where `--all` and its relatives mean "start from every ref".
WALK_COMMANDS = {"log", "rev-list", "shortlog", "show-branch", "grep", "show"}
REMOTE_COMMANDS = {"fetch", "pull", "ls-remote"}
REMOTE_BRANCH_FLAGS = {"-a", "-r", "--all", "--remotes"}
REMOTE_REF = re.compile(r"^(?:origin/|upstream/|remotes/|refs/remotes/)|@\{(?:u|upstream)\}$")
REFLOG_REF = re.compile(r"@\{\d+\}")
SHA = re.compile(r"[0-9a-f]{7,40}(?![0-9a-zA-Z_])")
# Commands that take a commit as an argument.
SHA_COMMANDS = {
    "show", "log", "diff", "checkout", "switch", "cherry-pick", "revert", "reset", "merge",
    "restore", "rev-list", "cat-file", "archive", "format-patch", "blame", "grep",
}  # fmt: skip


def command_reads(command: str) -> set[str]:
    """The kinds of future history that a shell command reads. Empty if it reads none."""
    kinds: set[str] = set()
    for segment in SEPARATORS.split(command):
        match = GIT_SEGMENT.match(segment.strip())
        if match:
            kinds |= _git_reads(_tokens(match.group(1)))
    return kinds


def _tokens(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:  # an unbalanced quote
        return text.split()


def _git_reads(tokens: list[str]) -> set[str]:
    subcommand, args = _split_subcommand(tokens)
    if any("://" in a or a.startswith("git@") for a in args):
        return set()
    kinds: set[str] = set()
    if subcommand in ALL_REFS_COMMANDS or (
        subcommand in WALK_COMMANDS and ALL_REFS_FLAGS & set(args)
    ):
        kinds.add("all_refs")
    if subcommand == "branch" and REMOTE_BRANCH_FLAGS & set(args):
        kinds.add("remote_ref")
    if subcommand in REMOTE_COMMANDS or any(REMOTE_REF.search(a) for a in args):
        kinds.add("remote_ref")
    if subcommand == "reflog" or any(REFLOG_REF.search(a) for a in args):
        kinds.add("reflog")
    if subcommand in SHA_COMMANDS and any(_names_commit(a) for a in args):
        kinds.add("sha")
    return kinds


def _split_subcommand(tokens: list[str]) -> tuple[str, list[str]]:
    """Skips git's own options, such as `-C /testbed`, and returns the subcommand and its words."""
    rest = iter(tokens)
    for token in rest:
        if token in GIT_OPTIONS_WITH_VALUE:
            next(rest, None)
        elif not token.startswith("-"):
            return token, list(rest)
    return "", []


def _names_commit(word: str) -> bool:
    """A hash has both digits and letters, which keeps out words such as `facade`."""
    hit = SHA.match(word)
    return bool(hit) and any(c.isdigit() for c in hit[0]) and any(c.isalpha() for c in hit[0])


def trajectory_commands(trajectory: Trajectory) -> list[str]:
    """Every shell command the agent ran."""
    return [
        call.arguments["command"]
        for message in trajectory.messages
        if message.role == "assistant"
        for call in message.tool_calls
        if call.name == BASH and isinstance(call.arguments.get("command"), str)
    ]


@dataclass(frozen=True)
class Counts:
    """Trajectories by `resolved` (the dict key). `any_read` counts those with a strong kind."""

    total: dict[bool, int]
    any_read: dict[bool, int]
    by_kind: dict[str, dict[bool, int]]
    examples: dict[str, list[str]] = field(default_factory=lambda: {})


def summarize(runs: Iterable[tuple[Sequence[str], bool]]) -> Counts:
    """Takes each trajectory's commands and whether it was resolved."""
    total = {True: 0, False: 0}
    any_read = {True: 0, False: 0}
    by_kind = {kind: {True: 0, False: 0} for kind in KINDS}
    examples: dict[str, list[str]] = defaultdict(list)
    for commands, resolved in runs:
        total[resolved] += 1
        found: set[str] = set()
        for command in commands:
            for kind in command_reads(command):
                found.add(kind)
                shown = examples[kind]
                if len(shown) < MAX_EXAMPLES and command not in shown:
                    shown.append(command)
        any_read[resolved] += bool(found & set(STRONG_KINDS))
        for kind in found:
            by_kind[kind][resolved] += 1
    return Counts(total, any_read, by_kind, dict(examples))


def _runs() -> Iterable[tuple[list[str], bool]]:
    """Streams the dataset in slices, because the file holds 2 GB of messages."""
    lazy = pl.scan_parquet(DATA_DIR / "trajectories/trajectories.parquet")
    rows = lazy.select(pl.len()).collect().item()
    for offset in range(0, rows, BATCH_ROWS):
        for row in lazy.slice(offset, BATCH_ROWS).collect().iter_rows(named=True):
            yield trajectory_commands(Trajectory.from_row(row)), row["resolved"] == 1


def main() -> None:
    counts = summarize(_runs())
    report = {
        "trajectories": {"resolved": counts.total[True], "unresolved": counts.total[False]},
        "any_read": {"resolved": counts.any_read[True], "unresolved": counts.any_read[False]},
        "by_kind": {
            kind: {"resolved": n[True], "unresolved": n[False]}
            for kind, n in counts.by_kind.items()
        },
        "examples": counts.examples,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "history_reads.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
