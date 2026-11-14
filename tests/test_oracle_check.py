import json
from pathlib import Path

import pytest

from grader_proof.oracle_check import (
    RunResult,
    TaskResult,
    parse_failing_tests,
    read_run,
    split_task_name,
)

PYTEST_OUTPUT = """\
==== short test summary info ====
PASSED tests/test_a.py::test_ok
FAILED tests/test_a.py::test_bad[x y] - assert 1 == 2
FAILED tests/test_b.py::TestC::test_worse
ERROR tests/test_c.py::test_setup - RuntimeError
==== 3 failed, 1 passed in 0.5s ====
"""


def make_trial(job: Path, reward: str | None, stdout: str = "") -> None:
    verifier = job / "trial-1" / "verifier"
    verifier.mkdir(parents=True)
    if reward is not None:
        (verifier / "reward.txt").write_text(reward)
    (verifier / "test-stdout.txt").write_text(stdout)


def test_parse_failing_tests_keeps_failed_and_error_ids() -> None:
    assert parse_failing_tests(PYTEST_OUTPUT) == [
        "tests/test_a.py::test_bad[x y]",
        "tests/test_b.py::TestC::test_worse",
        "tests/test_c.py::test_setup",
    ]


def test_parse_failing_tests_empty_when_all_pass() -> None:
    assert parse_failing_tests("PASSED tests/test_a.py::test_ok\n") == []


def test_split_task_name() -> None:
    assert split_task_name("12rambau__sepal_ui-411__baseline") == (
        "12rambau__sepal_ui-411",
        "baseline",
    )


def test_read_run_passing(tmp_path: Path) -> None:
    make_trial(tmp_path, "1\n", "PASSED tests/test_a.py::test_ok\n")
    assert read_run(tmp_path, run=2) == RunResult(run=2, reward=1, failing_tests=[])


def test_read_run_failing(tmp_path: Path) -> None:
    make_trial(tmp_path, "0\n", PYTEST_OUTPUT)
    run = read_run(tmp_path, run=1)
    assert run.reward == 0
    assert run.failing_tests[0] == "tests/test_a.py::test_bad[x y]"


def test_read_run_without_reward_file_has_no_reward(tmp_path: Path) -> None:
    (tmp_path / "trial-1").mkdir()
    assert read_run(tmp_path, run=1) == RunResult(run=1, reward=None, failing_tests=[])


def result(*rewards: int | None) -> TaskResult:
    runs = [RunResult(run=i, reward=r, failing_tests=[]) for i, r in enumerate(rewards, 1)]
    return TaskResult(task="t", condition="baseline", runs=runs)


def test_three_of_three_passes() -> None:
    assert result(1, 1, 1).passed
    assert not result(1, 1, 1).flaky


def test_one_failure_fails_and_is_flaky() -> None:
    assert not result(1, 0, 1).passed
    assert result(1, 0, 1).flaky


def test_consistent_failure_fails_but_is_not_flaky() -> None:
    assert not result(0, 0, 0).passed
    assert not result(0, 0, 0).flaky


def test_missing_reward_fails() -> None:
    assert not result(1, 1, None).passed


def test_fewer_than_three_runs_fails() -> None:
    assert not result(1, 1).passed


def test_task_result_round_trips_through_json() -> None:
    original = result(1, 0, 1)
    assert TaskResult.model_validate(json.loads(original.model_dump_json())) == original


@pytest.mark.parametrize("bad", ["", "no_condition"])
def test_split_task_name_rejects_names_without_condition(bad: str) -> None:
    with pytest.raises(ValueError, match="condition"):
        split_task_name(bad)
