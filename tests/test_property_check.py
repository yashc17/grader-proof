"""Runs H4's check, as `test.sh` defines it, on property checks written for these tests.

The check runs the task's `/tests/property_check.py` in isolated mode (ADR 0012). Each test puts a
script where the check expects it and reads the exit status: 0 accepts, anything else rejects.
"""

import os
import subprocess
from pathlib import Path

import pytest

from grader_proof.task_builder import CHECK_PROPERTY, PROPERTY_CHECK, render_property_check

# Exits 1 if `random` is not the standard library's, 0 otherwise.
USES_STDLIB_RANDOM = """\
import random
import sys

sys.exit(1 if hasattr(random, "PLANTED") else 0)
"""


def run_check(workspace: Path, script: str, env: dict[str, str] | None = None) -> int:
    """Writes `script` as the property check and runs H4's bash function in `workspace`."""
    check = workspace.parent / "grader/property_check.py"
    check.parent.mkdir(exist_ok=True)
    check.write_text(script)
    bash = render_property_check().replace(PROPERTY_CHECK, str(check)) + f"\n{CHECK_PROPERTY}\n"
    result = subprocess.run(["bash", "-c", bash], cwd=workspace, env=env, capture_output=True)
    return result.returncode


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "testbed"
    path.mkdir()
    return path


def test_check_accepts_a_property_that_holds(workspace: Path):
    assert run_check(workspace, "assert sorted([2, 1]) == [1, 2]\n") == 0


def test_check_rejects_a_property_that_fails(workspace: Path):
    assert run_check(workspace, "import sys\n\nsys.exit('clamp(-5, 0, 10) gave -5')\n") != 0


def test_check_rejects_a_property_that_raises(workspace: Path):
    assert run_check(workspace, "raise TypeError('unhashable')\n") != 0


def test_check_ignores_modules_planted_in_the_workspace_its_folder_or_pythonpath(
    workspace: Path, tmp_path: Path
):
    """The agent cannot write to the check's folder before grading, but it can leave files
    there for Harbor's copy to land next to. Isolated mode keeps all three folders off sys.path."""
    planted = tmp_path / "planted"
    grader = tmp_path / "grader"
    for folder in (workspace, planted, grader):
        folder.mkdir(exist_ok=True)
        (folder / "random.py").write_text("PLANTED = True\n")
    env = {**os.environ, "PYTHONPATH": f"{planted}:{workspace}"}
    assert run_check(workspace, USES_STDLIB_RANDOM, env) == 0
