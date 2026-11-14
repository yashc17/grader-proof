"""Runs the H1 restore step of `test.sh` against a real git repository.

The fixture builds a base commit, writes an upstream test patch that modifies, creates, deletes
and renames files, and applies it the way the task's Dockerfile does. Each test then plays the
agent, runs the restore step and checks what is on disk.
"""

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from grader_proof.task_builder import GRADING_PATCH, RESTORE, Instance, render_restore

BASE = {
    "src.py": "def f():\n    return 1\n",
    "tests/test_mod.py": "def test_a():\n    assert True\n",
    "tests/test_gone.py": "def test_old():\n    assert True\n",
    "tests/old_name.py": "HELPER = 1\n",
}

# Files as the upstream test patch leaves them. None means the patch deletes the file.
UPSTREAM: dict[str, str | None] = {
    "tests/test_mod.py": "def test_a():\n    assert True\n\n\ndef test_b():\n    assert f() == 2\n",
    "tests/test_new.py": "def test_new():\n    assert f() == 2\n",
    "tests/test_gone.py": None,
    "tests/old_name.py": None,
    "tests/new name.py": "HELPER = 1\n",
}

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, env=GIT_ENV, check=True, capture_output=True, text=True
    )
    return result.stdout


def write_files(repo: Path, files: Mapping[str, str | None]) -> None:
    for name, text in files.items():
        path = repo / name
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "testbed"
    repo.mkdir()
    git(repo, "init", "-q")
    write_files(repo, BASE)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    write_files(repo, UPSTREAM)
    git(repo, "add", "-A")
    (tmp_path / "upstream_tests.patch").write_text(git(repo, "diff", "--cached", "-M"))
    git(repo, "reset", "-q", "--hard")
    git(repo, "apply", str(tmp_path / "upstream_tests.patch"))
    return repo


@pytest.fixture
def instance(repo: Path) -> Instance:
    return Instance.model_validate(
        {
            "instance_id": "t__t-1",
            "base_commit": git(repo, "rev-parse", "HEAD").strip(),
            "problem_statement": "f returns 1",
            "patch": "",
            "test_patch": (repo.parent / "upstream_tests.patch").read_text(),
            "FAIL_TO_PASS": ["tests/test_mod.py::test_b"],
            "PASS_TO_PASS": [],
            "test_cmd": "pytest",
            "docker_image": "t",
        }
    )


def restore(repo: Path, instance: Instance) -> int:
    """Runs the restore step in `repo` and returns its exit status."""
    patch = str(repo.parent / "upstream_tests.patch")
    script = render_restore(instance).replace(GRADING_PATCH, patch) + f"\n{RESTORE}\n"
    return subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True).returncode


def assert_upstream(repo: Path) -> None:
    for name, text in UPSTREAM.items():
        path = repo / name
        assert (path.read_text() if path.exists() else None) == text, name


def test_restore_keeps_an_untouched_workspace(repo: Path, instance: Instance):
    assert restore(repo, instance) == 0
    assert_upstream(repo)


def test_restore_undoes_edits_to_every_touched_file(repo: Path, instance: Instance):
    write_files(
        repo,
        {
            "tests/test_mod.py": "def test_b():\n    pass\n",
            "tests/test_new.py": "def test_new():\n    pass\n",
            "tests/test_gone.py": "def test_old():\n    pass\n",
            "tests/old_name.py": "HELPER = 2\n",
            "tests/new name.py": "HELPER = 2\n",
        },
    )
    assert restore(repo, instance) == 0
    assert_upstream(repo)


def test_restore_brings_back_deleted_test_files(repo: Path, instance: Instance):
    write_files(repo, {"tests/test_mod.py": None, "tests/test_new.py": None})
    assert restore(repo, instance) == 0
    assert_upstream(repo)


def test_restore_ignores_commits_the_agent_made(repo: Path, instance: Instance):
    write_files(repo, {"tests/test_mod.py": "def test_b():\n    pass\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "agent")
    assert restore(repo, instance) == 0
    assert_upstream(repo)


def test_restore_leaves_files_the_patch_does_not_touch(repo: Path, instance: Instance):
    agent_files = {
        "src.py": "def f():\n    return 2\n",
        "tests/conftest.py": "collect_ignore = []\n",
    }
    write_files(repo, agent_files)
    assert restore(repo, instance) == 0
    assert_upstream(repo)
    for name, text in agent_files.items():
        assert (repo / name).read_text() == text


def test_restore_fails_without_git_history(repo: Path, instance: Instance):
    shutil.rmtree(repo / ".git")
    assert restore(repo, instance) != 0
