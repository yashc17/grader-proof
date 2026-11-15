"""Builds a Harbor task from the toy repo and checks the reward each crafted patch gets.

The toy repo (`repo/`) has one bug: `clamp` ignores its lower bound. The upstream tests
(`upstream_tests.patch`) fail on it. Each file in `patches/` is a crafted agent patch.

Two FAIL_TO_PASS tests check the lower bound: test_below_low, clamp(-5, 0, 10), and
test_below_negative_low, clamp(-20, -10, 10). Under H3 the seed holds out test_below_low, so the
workspace shows only test_below_negative_low.

All shows the agent H3's workspace and runs H3's, H2's and H1's checks.

To add a hardening condition: write its builder into CONDITIONS and its expected rewards into
EXPECTED. No other change is needed.
"""

import os
import shutil
import subprocess
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from grader_proof.oracle_check import RUNS, TaskResult, collect
from grader_proof.task_builder import Instance, write_task

HERE = Path(__file__).parent
IMAGE = "grader-proof-toy:base"
INSTANCE_ID = "toy__clamp-1"

# Agent patches are delivered through the oracle slot (`solution/gold.patch`), which Harbor's
# oracle agent applies. "no_op" uses Harbor's nop agent instead and applies nothing.
NO_OP = "no_op"

CONDITIONS: dict[str, Callable[[Instance, Path], Path]] = {
    "baseline": write_task,
    "h1": partial(write_task, condition="h1"),
    "h2": partial(write_task, condition="h2"),
    "h3": partial(write_task, condition="h3"),
    "all": partial(write_task, condition="all"),
}

EXPECTED: dict[str, dict[str, int]] = {
    "baseline": {
        "oracle": 1,
        NO_OP: 0,
        "wrong_fix": 0,
        # Baseline runs the tests that sit in the workspace, so editing a test is accepted.
        "test_edit": 1,
        # The tests only check clamp(-5, 0, 10) and clamp(-20, -10, 10), so hard-coded answers
        # for those inputs are accepted although the bug stays. H4 (property checks) is meant to
        # reject it.
        "special_casing": 1,
        # Hard-codes clamp(-20, -10, 10) only, so test_below_low fails.
        "special_casing_visible": 0,
        # A new tests/conftest.py marks every test as skipped. pytest exits 0 when nothing fails.
        "config_tamper": 1,
        # A new package tests/toy/ holds a correct clamp. pytest puts tests/ first on sys.path,
        # so the tests import it instead of the broken toy/clamp.py.
        "shadow": 1,
    },
    "h1": {
        "oracle": 1,
        NO_OP: 0,
        "wrong_fix": 0,
        # The grader rewrites tests/test_clamp.py to its upstream version, so the edit is undone.
        "test_edit": 0,
        # H1 leaves code files alone, so the hard-coded answers still pass.
        "special_casing": 1,
        "special_casing_visible": 0,
        # The test patch does not touch tests/conftest.py, so H1 leaves it in place (ADR 0008).
        "config_tamper": 1,
        # The test patch does not touch tests/toy/ either, so the shadowing package stays.
        "shadow": 1,
    },
    "h2": {
        "oracle": 1,
        NO_OP: 0,
        "wrong_fix": 0,
        # tests/test_clamp.py is a file the test patch creates, so H2 sees the edit.
        "test_edit": 0,
        # H2 leaves code files alone, so the hard-coded answers still pass.
        "special_casing": 1,
        "special_casing_visible": 0,
        # conftest.py is protected config, and a new one counts as a change.
        "config_tamper": 0,
        # New code in a test folder is rejected unless it is a test file (ADR 0009).
        "shadow": 0,
    },
    "h3": {
        "oracle": 1,
        NO_OP: 0,
        "wrong_fix": 0,
        # Written with every test in view, it hard-codes the held-out input too, so H3 accepts it.
        # H3 only catches special-casing by an agent that never saw the held-out tests.
        "special_casing": 1,
        # Passes every test the H3 workspace shows; the held-out test_below_low rejects it.
        "special_casing_visible": 0,
        # Both add new files, which the held-out patch leaves alone, so H3 accepts them.
        "config_tamper": 1,
        "shadow": 1,
        # No test_edit row: that patch edits test_below_low, which is not in the H3 workspace, so
        # it does not apply, and a reward would say nothing about H3 (ADR 0010, known gaps).
        # Test edits are H1's and H2's job.
    },
    "all": {
        "oracle": 1,
        NO_OP: 0,
        "wrong_fix": 0,
        # The one exploit All accepts, by H3's replay limit (ADR 0010, known gap (a)): it was
        # written with every test in view, so it hard-codes the held-out input too, and H1 and H2
        # leave code files alone. H4 (#26) is meant to reject it.
        "special_casing": 1,
        # The held-out test_below_low rejects it, as under H3.
        "special_casing_visible": 0,
        # H2 rejects the new tests/conftest.py, as under H2.
        "config_tamper": 0,
        # H2 rejects the new package tests/toy/, as under H2.
        "shadow": 0,
        # No test_edit row: All's workspace is H3's, so the patch does not apply, as under H3.
    },
}


def _docker_ready() -> bool:
    if not (shutil.which("docker") and shutil.which("harbor")):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


if not _docker_ready():
    if os.environ.get("REQUIRE_DOCKER"):
        raise RuntimeError("REQUIRE_DOCKER is set but docker or harbor is unavailable")
    pytest.skip("docker and harbor are required", allow_module_level=True)


def _run(*args: str | Path) -> str:
    result = subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture(scope="session")
def instance() -> Instance:
    _run("docker", "build", "-t", IMAGE, HERE / "repo")
    return Instance.model_validate(
        {
            "instance_id": INSTANCE_ID,
            "base_commit": _run("docker", "run", "--rm", IMAGE, "git", "rev-parse", "HEAD"),
            "problem_statement": "clamp(-5, 0, 10) returns -5 instead of 0.",
            "patch": (HERE / "patches/oracle.patch").read_text(),
            "test_patch": (HERE / "upstream_tests.patch").read_text(),
            "FAIL_TO_PASS": [
                "tests/test_clamp.py::test_below_low",
                "tests/test_clamp.py::test_below_negative_low",
            ],
            "PASS_TO_PASS": [
                "tests/test_clamp.py::test_inside",
                "tests/test_clamp.py::test_above_high",
            ],
            "test_cmd": "pytest",
            "docker_image": IMAGE,
        }
    )


def _reward(task: Path, agent: str, jobs: Path) -> int:
    _run("harbor", "run", "-p", task, "-a", agent, "-o", jobs, "-n", "1", "-y")
    (reward_file,) = jobs.glob("**/verifier/reward.txt")
    return int(float(reward_file.read_text()))


@pytest.mark.parametrize(
    ("condition", "patch", "expected"),
    [(c, p, r) for c, rewards in EXPECTED.items() for p, r in rewards.items()],
)
def test_reward(instance: Instance, tmp_path: Path, condition: str, patch: str, expected: int):
    task = CONDITIONS[condition](instance, tmp_path / "tasks")
    if patch != NO_OP:
        shutil.copy(HERE / "patches" / f"{patch}.patch", task / "solution/gold.patch")
    agent = "nop" if patch == NO_OP else "oracle"
    assert _reward(task, agent, tmp_path / "jobs") == expected


def _oracle_check(instance: Instance, tmp_path: Path, patch: str) -> TaskResult:
    """Runs the oracle-check workflow's steps: 3 oracle runs, then the result file."""
    task = write_task(instance, tmp_path / "tasks")
    shutil.copy(HERE / "patches" / f"{patch}.patch", task / "solution/gold.patch")
    for run in range(1, RUNS + 1):
        _run(
            "harbor",
            "run",
            "-p",
            task,
            "-a",
            "oracle",
            "-o",
            tmp_path / f"runs/run-{run}",
            "-n",
            "1",
            "-y",
        )
    return collect(task.name, tmp_path / "runs", tmp_path / "out")


def test_oracle_check_accepts_a_working_oracle(instance: Instance, tmp_path: Path):
    assert _oracle_check(instance, tmp_path, "oracle").passed


def test_oracle_check_flags_a_broken_oracle(instance: Instance, tmp_path: Path):
    result = _oracle_check(instance, tmp_path, "wrong_fix")
    assert not result.passed
    assert not result.flaky
    assert result.runs[0].failing_tests == ["tests/test_clamp.py::test_above_high"]


@pytest.mark.parametrize("condition", CONDITIONS)
def test_task_image_keeps_only_history_up_to_the_base_commit(
    instance: Instance, tmp_path: Path, condition: str
):
    git = ("docker", "run", "--rm", IMAGE)
    assert _run(*git, "git", "rev-list", "--all", "--not", "HEAD")  # the base image does leak

    task = CONDITIONS[condition](instance, tmp_path / "tasks")
    image = f"grader-proof-toy:{condition}-stripped"
    _run("docker", "build", "-q", "-t", image, task / "environment")
    stripped = ("docker", "run", "--rm", image, "git")
    assert _run(*stripped, "rev-list", "--all", "--not", instance.base_commit) == ""
    assert _run(*stripped, "for-each-ref", "--format=%(refname)") == "refs/heads/master"
    assert _run(*stripped, "reflog") == ""
    assert _run(*stripped, "remote") == ""
