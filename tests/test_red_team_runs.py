import tomllib
from pathlib import Path

import pytest

from grader_proof.red_team import TrialRecord
from grader_proof.red_team_runs import (
    MAX_CALL_USD,
    RunRecord,
    TrialKey,
    instances,
    is_infra_failure,
    pending,
    planned_trials,
    spend,
    summarize_runs,
    write_offline_task,
)

TASK_TOML = """\
[agent]
timeout_sec = 1800

[verifier]
timeout_sec = 600

[metadata]
visible_fail_to_pass = ["a"]
"""


def record(reward: int | None = 0, cost_usd: float = 0.05, truncated: int = 0) -> TrialRecord:
    return TrialRecord(
        task="demo__demo-1__baseline",
        task_path="runs/red-team-runs/tasks/demo__demo-1__baseline",
        trial="demo__demo-1__abc",
        instruction="prompts/red-team-v2.md",
        agent="terminus-2",
        agent_kwargs={"max_turns": 40},
        model="Qwen/Qwen3.5-9B-Base",
        reward=reward,
        turns=40,
        prompt_tokens=1000,
        cached_prompt_tokens=900,
        completion_tokens=100,
        cost_usd=cost_usd,
        agent_seconds=100.0,
        trial_seconds=150.0,
        exception=None,
        truncated_replies=truncated,
    )


def test_instances_come_from_baseline_folders(tmp_path: Path) -> None:
    for name in ("b__b-2__baseline", "b__b-2__all", "a__a-1__baseline", "a__a-1__h1"):
        (tmp_path / name).mkdir()

    assert instances(tmp_path) == ["a__a-1", "b__b-2"]


def test_planned_trials_run_one_task_at_a_time() -> None:
    planned = planned_trials(["a__a-1", "b__b-2"])

    assert len(planned) == 2 * 2 * 3
    assert {k.instance for k in planned[:6]} == {"a__a-1"}
    assert planned[0] == TrialKey(instance="a__a-1", condition="baseline", trial=1)
    assert planned[5] == TrialKey(instance="a__a-1", condition="all", trial=3)
    assert planned[0].name == "a__a-1__baseline__1"
    assert planned[0].task == "a__a-1__baseline"


def test_pending_skips_trials_with_a_result(tmp_path: Path) -> None:
    planned = planned_trials(["a__a-1"])
    (tmp_path / f"{planned[0].name}.json").write_text("{}")
    (tmp_path / f"{planned[3].name}.json").write_text("{}")

    assert pending(planned, tmp_path) == [planned[i] for i in (1, 2, 4, 5)]


def test_a_trial_without_a_reward_is_an_infra_failure() -> None:
    assert is_infra_failure(None)
    assert is_infra_failure(record(reward=None))
    assert not is_infra_failure(record(reward=0))
    assert not is_infra_failure(record(reward=1))


def test_spend_adds_an_upper_bound_for_truncated_replies() -> None:
    reported, upper = spend([record(cost_usd=0.05), record(cost_usd=0.02, truncated=3)])

    assert reported == pytest.approx(0.07)
    assert upper == pytest.approx(0.07 + 3 * MAX_CALL_USD)


def test_offline_task_turns_off_network_for_the_agent_only(tmp_path: Path) -> None:
    source = tmp_path / "tasks" / "a__a-1__baseline"
    (source / "environment").mkdir(parents=True)
    (source / "environment" / "Dockerfile").write_text("FROM x\n")
    (source / "task.toml").write_text(TASK_TOML)

    copy = write_offline_task(source, tmp_path / "copies")

    config = tomllib.loads((copy / "task.toml").read_text())
    assert copy == tmp_path / "copies" / "a__a-1__baseline"
    assert config["agent"] == {"timeout_sec": 1800, "network_mode": "no-network"}
    assert "network_mode" not in config["verifier"]
    assert (copy / "environment" / "Dockerfile").read_text() == "FROM x\n"
    assert (source / "task.toml").read_text() == TASK_TOML


def test_summary_counts_rewards_retries_and_failures(tmp_path: Path) -> None:
    keys = planned_trials(["a__a-1"])
    runs = [
        RunRecord(key=keys[0], attempts=1, record=record(reward=1, cost_usd=0.1)),
        RunRecord(key=keys[1], attempts=2, record=record(reward=0, cost_usd=0.2)),
        RunRecord(key=keys[3], attempts=2, record=None, failure="no reward"),
    ]
    for run in runs:
        (tmp_path / f"{run.key.name}.json").write_text(run.model_dump_json())

    summary = summarize_runs(tmp_path, planned=6)

    assert (summary.planned, summary.done, summary.retried, summary.failed) == (6, 3, 2, 1)
    assert summary.rewards == {"baseline": {"1": 1, "0": 1}, "all": {}}
    assert summary.spend_usd == pytest.approx(0.3)
