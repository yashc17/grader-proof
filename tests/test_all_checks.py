"""Runs the All condition's checks, in `test.sh`'s order, against a real git repository.

The fixture builds a base commit and an upstream test patch that adds two FAIL_TO_PASS tests to
one file and edits a second file. H3 holds one of the two tests out, and the fixture applies the
visible part the way the All task's Dockerfile does. Each test then plays the agent, runs the
checks and reads their exit status: 0 accepts, anything else rejects.

Both tests fail if the order changes: H2 before H3 would reject the untouched workspace, because
the held-out test is missing, and H1 before H2 would hide the edit H2 must reject.
"""

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from grader_proof.held_out import hold_out
from grader_proof.task_builder import (
    GRADING_PATCH,
    HELD_OUT_PATCH,
    Instance,
    render_checks,
)

BASE = {
    "src.py": "def f():\n    return 1\n",
    "tests/test_mod.py": "def test_a():\n    assert True\n",
    "tests/test_other.py": "def test_c():\n    assert True\n",
}

# Files as the upstream test patch leaves them.
UPSTREAM = {
    "tests/test_mod.py": (
        "def test_a():\n    assert True\n\n\n"
        "def test_one():\n    assert f() == 2\n\n\n"
        "def test_two():\n    assert f() + 1 == 3\n"
    ),
    "tests/test_other.py": "def test_c():\n    assert 1 + 1 == 2\n",
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


def write_files(repo: Path, files: Mapping[str, str]) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@pytest.fixture
def instance(tmp_path: Path) -> Instance:
    repo = tmp_path / "testbed"
    repo.mkdir()
    git(repo, "init", "-q")
    write_files(repo, BASE)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    write_files(repo, UPSTREAM)
    test_patch = git(repo, "diff")
    git(repo, "checkout", "-q", "--", ".")
    return Instance.model_validate(
        {
            "instance_id": "t__t-1",
            "base_commit": git(repo, "rev-parse", "HEAD").strip(),
            "problem_statement": "f returns 1",
            "patch": "",
            "test_patch": test_patch,
            "FAIL_TO_PASS": ["tests/test_mod.py::test_one", "tests/test_mod.py::test_two"],
            "PASS_TO_PASS": ["tests/test_mod.py::test_a", "tests/test_other.py::test_c"],
            "test_cmd": "pytest",
            "docker_image": "t",
        }
    )


@pytest.fixture
def repo(tmp_path: Path, instance: Instance) -> Path:
    """The All workspace: the base commit with the visible part of the test patch applied."""
    repo = tmp_path / "testbed"
    split = hold_out(instance.instance_id, instance.test_patch, instance.fail_to_pass)
    assert len(split.held_out) == 1
    (tmp_path / "upstream_tests.patch").write_text(instance.test_patch)
    (tmp_path / "held_out_tests.patch").write_text(split.held_out_patch)
    (tmp_path / "visible_tests.patch").write_text(split.visible_patch)
    git(repo, "apply", str(tmp_path / "visible_tests.patch"))
    return repo


def run_checks(repo: Path, instance: Instance) -> int:
    """Runs the All checks in `repo`, in `test.sh`'s order, and returns the exit status."""
    checks = render_checks(instance, "all")
    script = "".join(checks.values()) + "\n" + " && ".join(checks) + "\n"
    script = script.replace(GRADING_PATCH, str(repo.parent / "upstream_tests.patch"))
    script = script.replace(HELD_OUT_PATCH, str(repo.parent / "held_out_tests.patch"))
    return subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True).returncode


def test_all_accepts_an_untouched_workspace_and_restores_every_test(repo: Path, instance: Instance):
    assert run_checks(repo, instance) == 0
    for name, text in UPSTREAM.items():
        assert (repo / name).read_text() == text, name


def test_all_rejects_an_edit_to_a_test_file_that_h1_would_restore(repo: Path, instance: Instance):
    write_files(repo, {"tests/test_other.py": "def test_c():\n    assert True\n"})
    assert run_checks(repo, instance) != 0
