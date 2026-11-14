import json
from pathlib import Path

import pytest

from grader_proof.trajectory import (
    DEFAULT_MAX_TOKENS,
    Trajectory,
    condense,
    count_tokens,
    summarize_patch,
)

FIXTURES = Path(__file__).parent / "fixtures" / "trajectories"


def load(name: str) -> Trajectory:
    return Trajectory.from_row(json.loads((FIXTURES / f"{name}.json").read_text()))


def message(role: str, content: str = "", tool_calls: list[dict] | None = None) -> dict:
    return {
        "role": role,
        "content": content,
        "name": None,
        "tool_call_id": None,
        "tool_calls": tool_calls,
    }


def call(name: str, arguments: str) -> dict:
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}


def build(*messages: dict, patch: str = "") -> Trajectory:
    return Trajectory.from_row(
        {
            "trajectory_id": "t",
            "instance_id": "i",
            "repo": "r",
            "exit_status": "submit",
            "resolved": 0,
            "gen_tests_correct": None,
            "pred_passes_gen_tests": None,
            "model_patch": patch,
            "trajectory": list(messages),
        }
    )


def test_count_tokens_is_characters_over_four_rounded_up():
    assert count_tokens("") == 0
    assert count_tokens("abcd") == 1
    assert count_tokens("abcde") == 2


def test_string_arguments_are_parsed():
    trajectory = build(message("assistant", "", [call("execute_bash", '{"command": "ls"}')]))
    parsed = trajectory.messages[0].tool_calls[0]
    assert parsed.arguments == {"command": "ls"}
    assert parsed.parse_error is None


@pytest.mark.parametrize("raw", ['{"command": "ls', "[1, 2]", ""])
def test_unparsable_arguments_are_kept_as_text(raw: str):
    parsed = build(message("assistant", "", [call("execute_bash", raw)])).messages[0].tool_calls[0]
    assert parsed.arguments == {}
    assert parsed.raw_arguments == raw
    assert parsed.parse_error is not None


def test_unparsable_arguments_show_in_the_view():
    trajectory = build(message("assistant", "", [call("execute_bash", '{"command": "ls')]))
    view = condense(trajectory)
    assert any('{"command": "ls' in command for command in view.commands)
    assert any("unparsable arguments" in error for error in view.errors)
    assert '{"command": "ls' in view.text


def test_missing_patch_and_content_become_empty_text():
    row = json.loads((FIXTURES / "normal.json").read_text())
    row["model_patch"] = None
    row["trajectory"][0]["content"] = None
    trajectory = Trajectory.from_row(row)
    assert trajectory.model_patch == ""
    assert trajectory.messages[0].content == ""


def test_trajectory_is_frozen():
    with pytest.raises(ValueError, match="frozen"):
        load("normal").exit_status = "x"  # pyright: ignore[reportAttributeAccessIssue]


def test_summarize_patch_lists_files_test_files_and_line_counts():
    patch = (
        "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1,2 @@\n"
        "-old\n+new\n+newer\n"
        "diff --git a/tests/test_a.py b/tests/test_a.py\n--- a/tests/test_a.py\n"
        "+++ b/tests/test_a.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/conftest.py b/conftest.py\n+++ b/conftest.py\n+z\n"
    )
    summary = summarize_patch(patch)
    assert summary.files == ("src/a.py", "tests/test_a.py", "conftest.py")
    assert summary.test_files == ("tests/test_a.py", "conftest.py")
    assert (summary.added, summary.removed) == (4, 2)


def test_summarize_empty_patch():
    summary = summarize_patch("")
    assert summary.files == ()
    assert summary.test_files == ()


def test_normal_run():
    view = condense(load("normal"))
    assert view.exit_status == "submit"
    assert view.instance_id == "awisu2__imagenatepy-3"
    assert view.commands[-2:] == (
        "cd /workspace/awisu2__imagenatepy__unknown && imagenate",
        "finish",
    )
    assert any("git status" in command for command in view.commands)
    assert view.patch.files == ("issue.md", "src/imagenate/__init__.py", "src/imagenate/sample.py")
    assert view.patch.test_files == ()
    assert view.errors == ()
    assert view.last_observations[-1] == "hello\n[The command completed with exit code 0.]"
    assert "exit_status: submit" in view.text


def test_turn_limit_run():
    view = condense(load("turn_limit"))
    assert view.exit_status.startswith("RuntimeError: Agent reached max")
    assert "test_path_logic.py" in view.patch.test_files
    assert "cfdm/read_write/netcdf/netcdfread.py" in view.patch.files
    assert any(
        command.startswith("view /workspace/NCAS-CMS__cfdm__1.8") for command in view.commands
    )
    assert "Agent reached max" in view.text


def test_malformed_tool_call_is_reported_as_text():
    view = condense(load("malformed_tool_call"))
    assert any("tool call written as text" in error for error in view.errors)
    assert any("<tool_call>" in error for error in view.errors)
    assert "tool call written as text" in view.text
    assert view.patch.test_files == ("tests/test_arg_parse.py",)


def test_errors_come_from_exit_codes_and_error_observations():
    trajectory = build(
        message("assistant", "", [call("execute_bash", '{"command": "pytest"}')]),
        message(
            "tool",
            "collected 1 item\nE   ImportError: no module named foo\n"
            "[The command completed with exit code 1.]\n[Current working directory: /w]",
        ),
        message("assistant", "", [call("str_replace_editor", '{"command": "view", "path": "/x"}')]),
        message("tool", "ERROR:\nInvalid `view_range` parameter: [1, 50]."),
    )
    view = condense(trajectory)
    assert view.errors == (
        "#1: E   ImportError: no module named foo",
        "#3: Invalid `view_range` parameter: [1, 50].",
    )
    assert view.last_observations[0].endswith("[The command completed with exit code 1.]")
    assert "Current working directory" not in view.text


@pytest.mark.parametrize("name", ["normal", "turn_limit", "malformed_tool_call"])
@pytest.mark.parametrize("budget", [DEFAULT_MAX_TOKENS, 1000, 300])
def test_view_stays_under_the_budget(name: str, budget: int):
    view = condense(load(name), max_tokens=budget)
    assert count_tokens(view.text) <= budget


def test_long_trajectory_is_cut_to_the_budget_and_says_so():
    steps = []
    for n in range(300):
        steps.append(
            message("assistant", "", [call("execute_bash", json.dumps({"command": f"echo {n}"}))])
        )
        steps.append(message("tool", f"{n}\n[The command completed with exit code 0.]"))
    view = condense(build(*steps), max_tokens=500)
    assert count_tokens(view.text) <= 500
    assert "echo 0" in view.text
    assert "echo 299" in view.text
    assert "omitted" in view.text
    assert len(view.commands) == 300


def test_view_hides_labels_the_judge_must_not_see():
    row = json.loads((FIXTURES / "normal.json").read_text())
    text = condense(Trajectory.from_row(row)).text
    assert "resolved" not in text
    assert "gen_tests" not in text


def test_failed_command_without_output_is_still_an_error():
    trajectory = build(
        message("assistant", "", [call("execute_bash", '{"command": "grep x y"}')]),
        message(
            "tool",
            "\n[The command completed with exit code 1.]\n[Command finished with exit code 1]",
        ),
    )
    assert condense(trajectory).errors == ("#1: exit code 1, no output",)
