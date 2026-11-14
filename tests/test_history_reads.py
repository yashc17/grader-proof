import pytest

from grader_proof.history_reads import Counts, command_reads, summarize, trajectory_commands
from grader_proof.trajectory import Trajectory


@pytest.mark.parametrize(
    ("command", "kinds"),
    [
        ("git log --all --oneline -S 'def fix'", {"all_refs"}),
        ("cd /workspace/repo && git log --branches --remotes", {"all_refs"}),
        ("git rev-list --all | head", {"all_refs"}),
        ("git for-each-ref", {"all_refs"}),
        ("git log origin/main..HEAD", {"remote_ref"}),
        ("git checkout origin/main -- tests/", {"remote_ref"}),
        ("git branch -a", {"remote_ref"}),
        ("git -C /testbed diff origin/main", {"remote_ref"}),
        ("git fetch origin", {"remote_ref"}),
        ("git ls-remote origin", {"remote_ref"}),
        ("git reflog", {"reflog"}),
        ("git show HEAD@{2}", {"reflog"}),
        ("git show 1a2b3c4d5e", {"sha"}),
        ("git checkout 1a2b3c4 -- src/a.py", {"sha"}),
        ("git log --oneline deadbee1", {"sha"}),
        ("git ls-remote --tags https://github.com/o/r.git | head", set()),
        ("git fetch git@github.com:o/r.git", set()),
        ("git log --all && git reflog", {"all_refs", "reflog"}),
        ("GIT_PAGER=cat git log --all", {"all_refs"}),
        # Reads of the current history and of the working tree are not leaks.
        ("git log --oneline -5", set()),
        ("git show HEAD", set()),
        ("git show HEAD~3:setup.py", set()),
        ("git diff", set()),
        ("git status", set()),
        ("git log -n 3 --format=%H", set()),
        ("git stash list", set()),
        ("git describe --tags --all", set()),
        ("grep -r 'origin/main' docs/", set()),
        ("git commit -m 'decade facade'", set()),
        ("git log 'unbalanced", set()),
    ],
)
def test_command_reads(command: str, kinds: set[str]):
    assert command_reads(command) == kinds


def trajectory(*commands: str) -> Trajectory:
    calls = [
        {"id": "c", "type": "function", "function": {"name": "execute_bash", "arguments": a}}
        for a in [f'{{"command": "{c}"}}' for c in commands]
    ]
    calls.append(
        {
            "id": "e",
            "type": "function",
            "function": {"name": "str_replace_editor", "arguments": "{}"},
        }
    )
    return Trajectory.from_row(
        {
            "trajectory_id": "t",
            "instance_id": "i",
            "repo": "r",
            "exit_status": "submit",
            "model_patch": "",
            "trajectory": [
                {"role": "assistant", "content": "", "tool_calls": calls},
                {"role": "tool", "content": "git log --all", "tool_calls": None},
            ],
        }
    )


def test_trajectory_commands_are_the_bash_commands_the_agent_ran():
    assert trajectory_commands(trajectory("ls", "git log --all")) == ["ls", "git log --all"]


def test_summarize_splits_by_resolved():
    leaky = ["git log --all", "git reflog"]
    counts = summarize(
        [(leaky, True), (leaky, False), (["git show 1a2b3c4d"], False), (["git status"], True)]
    )
    assert counts == Counts(
        total={True: 2, False: 2},
        any_read={True: 1, False: 1},
        by_kind={
            "all_refs": {True: 1, False: 1},
            "remote_ref": {True: 0, False: 0},
            "reflog": {True: 1, False: 1},
            "sha": {True: 0, False: 1},
        },
        examples={
            "all_refs": ["git log --all"],
            "reflog": ["git reflog"],
            "sha": ["git show 1a2b3c4d"],
        },
    )
