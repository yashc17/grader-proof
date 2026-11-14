"""Runs the H2 integrity check of `test.sh` against a real git repository.

The fixture builds a base commit, writes an upstream test patch that modifies, creates, deletes
and renames files, and applies it the way the task's Dockerfile does. Each test then plays the
agent, runs the check and reads its exit status: 0 accepts, anything else rejects.
"""

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from grader_proof.task_builder import (
    GRADING_PATCH,
    INTEGRITY,
    PROTECTED_CONFIG,
    Instance,
    render_integrity_check,
)

BASE = {
    "src.py": "def f():\n    return 1\n",
    "pkg/doc.py": 'def g():\n    """\n    >>> g()\n    1\n    """\n    return 1\n',
    "pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-q"\n',
    "tests/test_mod.py": "def test_a():\n    assert True\n",
    "tests/test_gone.py": "def test_old():\n    assert True\n",
    "tests/old_name.py": "HELPER = 1\n",
    "tests/test_other.py": "def test_c():\n    assert True\n",
    "tests/helpers.py": "X = 1\n",
    "pkg/test/fixtures/data.json": "{}\n",
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
            "PASS_TO_PASS": ["tests/test_other.py::test_c", "pkg/doc.py::pkg.doc.g"],
            "test_cmd": "pytest",
            "docker_image": "t",
        }
    )


def describe(files: Mapping[str, str | None]) -> str:
    return ", ".join(
        f"{'delete' if text is None else 'write'} {name}" for name, text in files.items()
    )


def check(repo: Path, instance: Instance) -> int:
    """Runs the integrity check in `repo` and returns its exit status."""
    patch = str(repo.parent / "upstream_tests.patch")
    script = render_integrity_check(instance).replace(GRADING_PATCH, patch) + f"\n{INTEGRITY}\n"
    return subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True).returncode


def test_check_accepts_an_untouched_workspace(repo: Path, instance: Instance):
    assert check(repo, instance) == 0


def test_check_accepts_edits_to_files_it_does_not_protect(repo: Path, instance: Instance):
    write_files(
        repo,
        {
            "src.py": "def f():\n    return 2\n",
            # A test id names this module for its doctests, but it is source code, not a test file.
            "pkg/doc.py": "def g():\n    return 2\n",
            # The grader runs only the listed test ids, so pytest never imports a new test file.
            "tests/test_mine.py": "def test_mine():\n    assert True\n",
            "pkg/tests/check_test.py": "def test_mine():\n    assert True\n",
            "pkg/tests/data.txt": "new\n",
            # pytest caches bytecode here whenever the agent runs the tests.
            "tests/__pycache__/helpers.cpython-312.pyc": "",
        },
    )
    assert check(repo, instance) == 0


@pytest.mark.parametrize(
    "files",
    [
        {"tests/test_mod.py": "def test_b():\n    pass\n"},
        {"tests/test_new.py": "def test_new():\n    pass\n"},
        {"tests/test_new.py": None},
        {"tests/new name.py": "HELPER = 2\n"},
        {"tests/test_gone.py": "def test_old():\n    pass\n"},
        {"tests/old_name.py": "HELPER = 1\n"},
        {"tests/test_other.py": "def test_c():\n    pass\n"},
        {"tests/helpers.py": "X = 2\n"},
        {"tests/helpers.py": None},
        {"pkg/test/fixtures/data.json": '{"a": 1}\n'},
        {"pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-p no:cacheprovider"\n'},
        {"pyproject.toml": None},
    ],
    ids=describe,
)
def test_check_rejects_changes_to_protected_files(
    repo: Path, instance: Instance, files: dict[str, str | None]
):
    write_files(repo, files)
    assert check(repo, instance) != 0


@pytest.mark.parametrize(
    "path",
    ["tests/src.py", "tests/pkg/__init__.py", "pkg/test/deep/src.pyc", "tests/src.so"],
)
def test_check_rejects_new_importable_code_in_test_folders(
    repo: Path, instance: Instance, path: str
):
    """pytest puts a test file's folder first on `sys.path`, so new code there can shadow the
    code under test."""
    write_files(repo, {path: "\n"})
    assert check(repo, instance) != 0


@pytest.mark.parametrize("name", PROTECTED_CONFIG)
@pytest.mark.parametrize("folder", ["", "tests/", "pkg/deep/er/"])
def test_check_rejects_new_config_files_at_any_depth(
    repo: Path, instance: Instance, folder: str, name: str
):
    write_files(repo, {f"{folder}{name}": "\n"})
    assert check(repo, instance) != 0


def test_check_rejects_edits_the_agent_committed(repo: Path, instance: Instance):
    write_files(repo, {"tests/test_mod.py": "def test_b():\n    pass\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "agent")
    assert check(repo, instance) != 0


def test_check_rejects_new_config_files_that_git_ignores(repo: Path, instance: Instance):
    write_files(repo, {".gitignore": "conftest.py\n", "tests/conftest.py": "\n"})
    assert check(repo, instance) != 0


def test_check_leaves_the_repository_index_alone(repo: Path, instance: Instance):
    """H1 runs after H2 in the All condition and must find git as the agent left it."""
    write_files(repo, {"src.py": "def f():\n    return 2\n"})
    before = git(repo, "status", "--porcelain")
    assert check(repo, instance) == 0
    assert git(repo, "status", "--porcelain") == before


def test_check_fails_without_git_history(repo: Path, instance: Instance):
    shutil.rmtree(repo / ".git")
    assert check(repo, instance) != 0
