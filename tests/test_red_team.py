import json
import subprocess
from pathlib import Path

import pytest

from grader_proof.red_team import agent_patch, read_trial

TESTS_PATCH = """\
--- a/test_calc.py
+++ b/test_calc.py
@@ -1 +1,2 @@
 from calc import add
+assert add(1, 1) == 2
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    """A repo at its base commit with the tests patch applied but not committed, as in Baseline."""
    repo = tmp_path / "testbed"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "test_calc.py").write_text("from calc import add\n")
    (repo / ".gitignore").write_text("__pycache__/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    git(repo, "reflog", "expire", "--expire=now", "--all")
    tests_patch = tmp_path / "upstream_tests.patch"
    tests_patch.write_text(TESTS_PATCH)
    git(repo, "apply", str(tests_patch))
    return repo, tests_patch


def test_untouched_workspace_has_empty_patch(workspace: tuple[Path, Path]) -> None:
    repo, tests_patch = workspace
    assert agent_patch(repo, tests_patch) == ""


def test_patch_holds_agent_edits_but_not_the_tests_patch(
    workspace: tuple[Path, Path],
) -> None:
    repo, tests_patch = workspace
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "notes.txt").write_text("new file\n")

    patch = agent_patch(repo, tests_patch)

    assert "+    return a + b" in patch
    assert "notes.txt" in patch
    assert "assert add(1, 1) == 2" not in patch


def test_patch_shows_edits_to_upstream_tests(workspace: tuple[Path, Path]) -> None:
    repo, tests_patch = workspace
    (repo / "test_calc.py").write_text("from calc import add\n")

    patch = agent_patch(repo, tests_patch)

    assert "-assert add(1, 1) == 2" in patch


def test_patch_skips_ignored_files(workspace: tuple[Path, Path]) -> None:
    repo, tests_patch = workspace
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "calc.pyc").write_bytes(b"\x00")

    assert agent_patch(repo, tests_patch) == ""


def test_patch_counts_committed_edits(workspace: tuple[Path, Path]) -> None:
    repo, tests_patch = workspace
    (repo / "calc.py").write_text("def add(a, b):\n    return 2\n")
    git(repo, "commit", "--quiet", "-am", "agent commit")

    patch = agent_patch(repo, tests_patch)

    assert "+    return 2" in patch
    assert "assert add(1, 1) == 2" not in patch


def test_patch_leaves_the_repo_index_alone(workspace: tuple[Path, Path]) -> None:
    repo, tests_patch = workspace
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    status_before = git(repo, "status", "--porcelain")

    agent_patch(repo, tests_patch)

    assert git(repo, "status", "--porcelain") == status_before


def test_patch_applies_to_a_fresh_workspace(workspace: tuple[Path, Path], tmp_path: Path) -> None:
    repo, tests_patch = workspace
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "test_calc.py").unlink()
    patch_file = tmp_path / "agent.patch"
    patch_file.write_text(agent_patch(repo, tests_patch))

    fresh = tmp_path / "fresh"
    git(tmp_path, "clone", "--quiet", str(repo), str(fresh))
    git(fresh, "apply", str(tests_patch))
    git(fresh, "apply", str(patch_file))

    assert (fresh / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"
    assert not (fresh / "test_calc.py").exists()


def write_result(trial: Path, reward: float | None) -> None:
    trial.mkdir(parents=True)
    result = {
        "task_name": "demo__demo-1__baseline",
        "trial_name": "demo__demo-1__abc",
        "config": {"agent": {"name": "terminus-2", "kwargs": {"max_turns": 40}}},
        "agent_info": {"model_info": {"name": "Qwen/Qwen3.5-9B-Base"}},
        "agent_result": {
            "n_input_tokens": 4721,
            "n_cache_tokens": 1792,
            "n_output_tokens": 383,
            "cost_usd": 0.001295301,
            "metadata": {"n_episodes": 2},
        },
        "verifier_result": None if reward is None else {"rewards": {"reward": reward}},
        "exception_info": None,
        "started_at": "2026-11-15T02:55:55.951328Z",
        "finished_at": "2026-11-15T02:57:17.233452Z",
        "agent_execution": {
            "started_at": "2026-11-15T02:56:53.474488Z",
            "finished_at": "2026-11-15T02:57:05.378876Z",
        },
    }
    (trial / "result.json").write_text(json.dumps(result))


def test_read_trial_takes_usage_reward_and_times(tmp_path: Path) -> None:
    trial = tmp_path / "demo__demo-1__abc"
    write_result(trial, reward=1.0)

    record = read_trial(trial)

    assert record.task == "demo__demo-1__baseline"
    assert record.agent == "terminus-2"
    assert record.agent_kwargs == {"max_turns": 40}
    assert record.model == "Qwen/Qwen3.5-9B-Base"
    assert record.reward == 1
    assert record.turns == 2
    assert record.prompt_tokens == 4721
    assert record.cached_prompt_tokens == 1792
    assert record.completion_tokens == 383
    assert record.cost_usd == pytest.approx(0.001295301)
    assert record.agent_seconds == pytest.approx(11.9, abs=0.1)
    assert record.trial_seconds == pytest.approx(81.3, abs=0.1)
    assert record.exception is None


def test_read_trial_without_verifier_has_no_reward(tmp_path: Path) -> None:
    trial = tmp_path / "demo__demo-1__abc"
    write_result(trial, reward=None)

    assert read_trial(trial).reward is None
