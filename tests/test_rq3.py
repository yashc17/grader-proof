import json
from pathlib import Path

import pytest

from grader_proof.exploit_review import Verdict
from grader_proof.oracle_check import RunResult, TaskResult
from grader_proof.replay import Outcome, ReplayResult
from grader_proof.rq3 import (
    Attempt,
    Estimate,
    build_rows,
    effect,
    exploit_rate,
    missing_verdicts,
    read_adaptive,
    read_oracle,
    read_replay,
    render_markdown,
    write_csv,
)


def attempt(trial: str, condition: str, outcome: Outcome, task: str = "a") -> Attempt:
    return Attempt(task=task, trial=trial, condition=condition, outcome=outcome)


def exploit(trial: str, category: str = "edits_tests", task: str = "a__baseline") -> Verdict:
    return Verdict.model_validate(
        {"trial": trial, "task": task, "verdict": "exploit", "category": category}
    )


def real_fix(trial: str) -> Verdict:
    return Verdict(trial=trial, task="a__baseline", verdict="real_fix")


def test_exploit_rate_counts_accepted_exploits_over_graded_attempts():
    attempts = [
        attempt("x1", "baseline", "accepted"),
        attempt("x2", "baseline", "accepted"),
        attempt("x3", "baseline", "rejected"),
        attempt("x4", "baseline", "not_applied"),
    ]
    assert exploit_rate(attempts, {"x1"}, interval=False) == Estimate(n=3, value=1 / 3)


def test_exploit_rate_is_none_when_nothing_was_graded():
    attempts = [attempt("x1", "h3", "not_applied")]
    assert exploit_rate(attempts, {"x1"}, interval=True) == Estimate(n=0)


def test_effect_pairs_attempts_by_trial_and_skips_patches_that_did_not_apply():
    baseline = [
        attempt("x1", "baseline", "accepted"),
        attempt("x2", "baseline", "accepted"),
        attempt("x3", "baseline", "rejected"),
    ]
    technique = [
        attempt("x1", "h3", "rejected"),
        attempt("x2", "h3", "not_applied"),
        attempt("x3", "h3", "rejected"),
    ]
    assert effect(baseline, technique, {"x1", "x2"}, interval=False) == Estimate(n=2, value=0.5)


def test_intervals_resample_whole_tasks():
    """Task a is all exploits and task b none. Resampling tasks, a quarter of the resamples draw
    only a and a quarter only b, so the interval spans 0 to 1. Resampling attempts one by one
    would give a much narrower one."""
    attempts = [attempt(f"a{i}", "baseline", "accepted", task="a") for i in range(5)]
    attempts += [attempt(f"b{i}", "baseline", "rejected", task="b") for i in range(5)]
    exploits = {f"a{i}" for i in range(5)}
    assert exploit_rate(attempts, exploits, interval=True) == Estimate(
        n=10, value=0.5, low=0.0, high=1.0
    )


def test_intervals_use_a_fixed_seed():
    attempts = [attempt(f"{t}{i}", "baseline", "accepted", task=t) for t in "abc" for i in range(2)]
    first = exploit_rate(attempts, {"a0", "b1"}, interval=True)
    assert first == exploit_rate(attempts, {"a0", "b1"}, interval=True)
    assert first.low is not None
    assert first.high is not None
    assert first.low <= 1 / 3 <= first.high


def test_missing_verdicts_lists_accepted_trials_without_one():
    attempts = [
        attempt("x1", "baseline", "accepted"),
        attempt("x1", "h1", "accepted"),
        attempt("x2", "h1", "accepted"),
        attempt("x3", "baseline", "rejected"),
    ]
    assert missing_verdicts(attempts, [exploit("x1")]) == ["x2"]


def test_read_adaptive_reads_the_red_team_summary(tmp_path: Path):
    summary = tmp_path / "red_team.json"
    trials = [
        {"trial": "x1", "task_path": "tasks/a__baseline", "reward": 1, "turns": 3},
        {"trial": "x2", "task_path": "tasks/a__all", "reward": 0},
        {"trial": "x3", "task_path": "tasks/b__all", "reward": None},
    ]
    summary.write_text(json.dumps({"trials": trials, "projections": []}))
    assert read_adaptive(summary) == [
        attempt("x1", "baseline", "accepted"),
        attempt("x2", "all", "rejected"),
        attempt("x3", "all", "no_reward", task="b"),
    ]


def test_read_replay_reads_every_result_file(tmp_path: Path):
    results = [
        ReplayResult(task="a", trial="x1", condition="h1", outcome="accepted", failing_tests=[]),
        ReplayResult(task="a", trial="x2", condition="h1", outcome="rejected", failing_tests=[]),
    ]
    folder = tmp_path / "replay-a__h1"
    folder.mkdir()
    (folder / "a__h1.json").write_text(json.dumps([r.model_dump() for r in results]))
    assert read_replay(tmp_path) == [
        attempt("x1", "h1", "accepted"),
        attempt("x2", "h1", "rejected"),
    ]


def test_read_oracle_counts_accepted_runs_per_task_and_condition(tmp_path: Path):
    runs = [RunResult(run=i, reward=r, failing_tests=[]) for i, r in enumerate((1, 0, 1), 1)]
    (tmp_path / "a__h2.json").write_text(
        TaskResult(task="a", condition="h2", runs=runs).model_dump_json()
    )
    assert read_oracle(tmp_path) == {("a", "h2"): (2, 3)}


@pytest.fixture
def rows():
    replay = [
        attempt("x1", "baseline", "accepted"),
        attempt("x2", "baseline", "accepted", task="b"),
        attempt("x1", "h1", "rejected"),
        attempt("x2", "h1", "accepted", task="b"),
        attempt("x1", "h3", "not_applied"),
        attempt("x2", "h3", "accepted", task="b"),
    ]
    adaptive = [
        attempt("x1", "baseline", "accepted"),
        attempt("x2", "baseline", "accepted", task="b"),
        attempt("y1", "all", "rejected"),
        attempt("y2", "all", "no_reward", task="b"),
    ]
    verdicts = [exploit("x1"), exploit("x2", "stubs_outputs", "b__baseline")]
    oracle = {("a", "baseline"): (3, 3), ("b", "baseline"): (3, 3), ("a", "h1"): (2, 3)}
    return build_rows(replay, adaptive, verdicts, oracle)


def test_build_rows_has_a_row_for_all_tasks_then_one_per_task(rows):
    assert [(r.scope, r.condition) for r in rows] == [
        ("all", "baseline"),
        ("all", "h1"),
        ("all", "h3"),
        ("all", "all"),
        ("a", "baseline"),
        ("a", "h1"),
        ("a", "h3"),
        ("a", "all"),
        ("b", "baseline"),
        ("b", "h1"),
        ("b", "h3"),
        ("b", "all"),
    ]


def test_build_rows_all_tasks_row(rows):
    h1 = rows[1]
    assert (h1.replay_attempts, h1.replay_ungraded, h1.replay_exploits) == (2, 0, 1)
    assert h1.replay_rate.value == 0.5
    assert h1.effect is not None
    assert h1.effect.value == 0.5
    assert h1.replay_categories == {"stubs_outputs": 1}
    assert (h1.oracle_accepted, h1.oracle_runs) == (2, 3)
    assert h1.adaptive_rate is None

    everything = rows[3]
    assert (everything.adaptive_attempts, everything.adaptive_ungraded) == (2, 1)
    assert everything.adaptive_rate == Estimate(n=1, value=0.0, low=0.0, high=0.0)


def test_build_rows_keeps_patches_that_did_not_apply_out_of_the_rate(rows):
    h3_a = rows[6]
    assert (h3_a.replay_attempts, h3_a.replay_ungraded) == (1, 1)
    assert h3_a.replay_rate == Estimate(n=0)
    assert h3_a.effect == Estimate(n=0)


def test_per_task_rows_have_no_intervals(rows):
    assert rows[4].replay_rate == Estimate(n=1, value=1.0)


def test_baseline_has_no_effect(rows):
    assert rows[0].effect is None
    assert rows[0].replay_categories == {"edits_tests": 1, "stubs_outputs": 1}


def test_write_csv_has_one_line_per_row(rows, tmp_path: Path):
    path = tmp_path / "rq3.csv"
    write_csv(rows, path)
    lines = path.read_text().splitlines()
    assert len(lines) == len(rows) + 1
    assert lines[0].startswith("scope,condition,adaptive_attempts,")
    assert lines[2].startswith("all,h1,0,0,0,,,,2,0,1,0.5,")


def test_render_markdown_shows_rates_with_intervals(rows):
    table = render_markdown(rows)
    assert "| all | baseline |" in table
    assert "2/2 = 100% [100%, 100%]" in table
    assert "| a | h1 |" in table
