import json
from pathlib import Path

from grader_proof.fact_sheet import (
    TEMPLATE_PATH,
    TURN_LIMIT,
    actions,
    agent_test_runs,
    ending,
    is_hidden,
    is_test_command,
    pair_files,
    split_patch,
)
from grader_proof.labeling import FAILURE_CLASSES, FOOLED_REASONS
from grader_proof.trajectory import Trajectory

FIXTURES = Path(__file__).parent / "fixtures" / "trajectories"


def load(name: str) -> Trajectory:
    return Trajectory.from_row(json.loads((FIXTURES / f"{name}.json").read_text()))


def bash(call_id: str, command: str) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "name": None,
        "tool_call_id": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "execute_bash", "arguments": json.dumps({"command": command})},
            }
        ],
    }


def tool(call_id: str, content: str) -> dict:
    return {
        "role": "tool",
        "content": content,
        "name": "execute_bash",
        "tool_call_id": call_id,
        "tool_calls": None,
    }


def build(*messages: dict, exit_status: str = "submit") -> Trajectory:
    return Trajectory.from_row(
        {
            "trajectory_id": "t",
            "instance_id": "i",
            "repo": "r",
            "exit_status": exit_status,
            "model_patch": "",
            "trajectory": list(messages),
        }
    )


def diff(path: str, body: str = "@@ -1 +1 @@\n-a\n+b\n") -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n{body}"


PYTEST_OUTPUT = """\
============================= test session starts ==============================
collected 3 items

tests/test_x.py ..F                                                       [100%]

=========================== short test summary info ============================
FAILED tests/test_x.py::test_three - AssertionError: 1 != 2
========================= 1 failed, 2 passed in 0.12s ==========================
[The command completed with exit code 1.]
[Current working directory: /workspace/x]"""

UNITTEST_OUTPUT = """\
...
----------------------------------------------------------------------
Ran 3 tests in 0.001s

OK
[The command completed with exit code 0.]"""


def test_split_patch_keys_each_file_section_by_its_new_path():
    patch = diff("a.py") + diff("pkg/b.py")
    sections = split_patch(patch)
    assert list(sections) == ["a.py", "pkg/b.py"]
    assert sections["pkg/b.py"] == diff("pkg/b.py").rstrip("\n")


def test_split_patch_of_an_empty_patch_is_empty():
    assert split_patch("") == {}


def test_is_hidden_covers_dot_folders_and_bytecode():
    assert is_hidden(".hypothesis/examples/abc")
    assert is_hidden("pkg/__pycache__/mod.cpython-39.pyc")
    assert is_hidden("mod.pyc")
    assert is_hidden("src/pkg.egg-info/PKG-INFO")
    assert not is_hidden("pkg/mod.py")
    assert not is_hidden("tests/test_mod.py")


def test_pair_files_lists_shared_files_first_then_one_sided_then_hidden():
    agent = diff("z.py") + diff("only_agent.py") + diff(".hypothesis/x") + diff("a.py")
    gold = diff("a.py") + diff("only_gold.py") + diff("z.py")
    files = pair_files(agent, gold)
    assert [f.path for f in files] == [
        "a.py",
        "z.py",
        "only_agent.py",
        "only_gold.py",
        ".hypothesis/x",
    ]
    assert [f.shared for f in files] == [True, True, False, False, False]
    assert files[2].gold is None
    assert files[3].agent is None
    assert files[4].hidden


def test_is_test_command_matches_test_runners_and_test_scripts():
    assert is_test_command("cd /w && python -m pytest tests/ -v")
    assert is_test_command("pytest -x tests/test_a.py::test_b")
    assert is_test_command("python -m unittest tests.test_sample -v")
    assert is_test_command("python test_reproduction.py")
    assert is_test_command("python3 /workspace/repo/tests/test_fix.py")
    assert is_test_command("tox -e py39")
    assert not is_test_command("python reproduce_issue.py")
    assert not is_test_command("rm -rf tests/ test_reproduction.py")
    assert not is_test_command("pip install pytest")
    assert not is_test_command("grep -rn pytest setup.cfg")


def test_actions_pair_each_call_with_its_observation_by_id():
    trajectory = build(
        bash("c1", "ls"), tool("c1", "a.py\n[The command completed with exit code 0.]")
    )
    (action,) = actions(trajectory)
    assert action.command == "ls"
    assert action.observation is not None
    assert action.observation.startswith("a.py")


def test_actions_from_a_real_trajectory_pair_the_pytest_call_with_its_output():
    found = actions(load("normal"))
    pytest_runs = [a for a in found if "python -m pytest tests/ -v" in a.command]
    assert len(pytest_runs) == 1
    assert "PytestDeprecationWarning" in (pytest_runs[0].observation or "")


def test_agent_test_runs_quote_the_pytest_summary_and_exit_code():
    trajectory = build(
        bash("c1", "python -m pytest tests/"),
        tool("c1", PYTEST_OUTPUT),
        bash("c2", "cat setup.py"),
        tool("c2", "setup()\n[The command completed with exit code 0.]"),
    )
    (run,) = agent_test_runs(actions(trajectory))
    assert run.command == "python -m pytest tests/"
    assert run.exit_code == "1"
    assert run.summary == (
        "FAILED tests/test_x.py::test_three - AssertionError: 1 != 2",
        "========================= 1 failed, 2 passed in 0.12s ==========================",
    )


def test_agent_test_runs_quote_the_unittest_summary():
    trajectory = build(bash("c1", "python -m unittest"), tool("c1", UNITTEST_OUTPUT))
    (run,) = agent_test_runs(actions(trajectory))
    assert run.exit_code == "0"
    assert run.summary == ("Ran 3 tests in 0.001s", "OK")


def test_agent_test_run_without_a_summary_line_keeps_the_last_output_lines():
    trajectory = build(
        bash("c1", "python test_fix.py"),
        tool("c1", "start\nvalue: 3\nall good\n[The command completed with exit code 0.]"),
    )
    (run,) = agent_test_runs(actions(trajectory))
    assert run.summary == ()
    assert run.last_lines == ("start", "value: 3", "all good")


def test_agent_test_run_with_output_cut_off_has_no_exit_code():
    (run,) = [r for r in agent_test_runs(actions(load("normal"))) if "pytest" in r.command]
    assert run.exit_code is None


def test_ending_of_a_run_stopped_at_the_turn_limit():
    trajectory = load("turn_limit")
    end = ending(trajectory, actions(trajectory))
    assert end.turns == 10  # the fixture keeps 22 of the run's 201 messages
    assert end.limit == TURN_LIMIT == 100
    assert end.exit_status.startswith("RuntimeError: Agent reached maximum iteration")
    assert len(end.last_actions) == 3
    # The run stopped before its last call got an observation.
    assert end.last_actions[-1].command.startswith("cd /workspace/NCAS-CMS__cfdm__1.8 && grep")
    assert end.last_actions[-1].observation is None


def test_ending_keeps_the_last_three_actions_in_order():
    trajectory = build(
        *(m for i in range(5) for m in (bash(f"c{i}", f"echo {i}"), tool(f"c{i}", f"{i}"))),
        exit_status="AgentStuckInLoopError: Agent got stuck in a loop",
    )
    end = ending(trajectory, actions(trajectory))
    assert [a.command for a in end.last_actions] == ["echo 2", "echo 3", "echo 4"]
    assert end.turns == 5
    assert end.exit_status == "AgentStuckInLoopError: Agent got stuck in a loop"


def test_template_names_no_failure_class_or_fooled_reason():
    """The sheets are the answer key for #14, so the page itself must not suggest a label."""
    template = TEMPLATE_PATH.read_text().lower()
    for word in (*FAILURE_CLASSES, *FOOLED_REASONS, "likely", "probably", "seems"):
        assert word.lower().replace("_", " ") not in template.replace("_", " "), word
