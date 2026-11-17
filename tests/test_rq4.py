from pathlib import Path

import pytest

from grader_proof.red_team import TrialRecord
from grader_proof.red_team_runs import RunRecord, TrialKey
from grader_proof.rq4 import load_models, model_result

NINE_B = "Qwen/Qwen3.5-9B-Base"


def run(instance: str, trial: int, reward: int | None, model: str = NINE_B) -> RunRecord:
    record = TrialRecord(
        task=f"{instance}__all",
        task_path=f"runs/rq4/tasks/{instance}__all",
        trial=f"{instance}__all__abc{trial}",
        instruction=None,
        agent="terminus-2",
        agent_kwargs={"max_turns": 40},
        model=model,
        reward=reward,
        turns=10,
        prompt_tokens=1000,
        cached_prompt_tokens=900,
        completion_tokens=100,
        cost_usd=0.03,
        agent_seconds=100.0,
        trial_seconds=150.0,
        exception=None if reward is not None else "AgentTimeoutError",
        truncated_replies=0,
    )
    key = TrialKey(instance=instance, condition="all", trial=trial)
    return RunRecord(key=key, attempts=1, record=record)


def rewards(instance: str, *values: int | None) -> list[RunRecord]:
    return [run(instance, trial, reward) for trial, reward in enumerate(values, 1)]


def test_mean_pass_rate_is_the_mean_over_tasks_of_each_task_pass_rate():
    runs = [*rewards("a", 1, 1, 1), *rewards("b", 0, 0, 0), *rewards("c", 1, 0, 0)]
    result = model_result(NINE_B, runs)
    assert result.per_task == {"a": pytest.approx(1), "b": 0, "c": pytest.approx(1 / 3)}
    assert result.mean_pass_rate == pytest.approx((1 + 0 + 1 / 3) / 3)
    assert result.low <= result.mean_pass_rate <= result.high
    assert (result.tasks, result.trials) == (3, 9)


def test_distribution_counts_tasks_by_passes_out_of_trials():
    runs = [*rewards("a", 1, 1, 1), *rewards("b", 0, 0, 0), *rewards("c", 0, 0, 0)]
    assert model_result(NINE_B, runs).distribution == {"0/3": 2, "3/3": 1}


def test_trials_without_a_reward_are_left_out_and_counted():
    runs = [*rewards("a", 1, None, 1), *rewards("b", 0, 0, 0)]
    result = model_result(NINE_B, runs)
    assert result.per_task["a"] == 1
    assert result.no_reward == 1
    assert result.distribution == {"0/3": 1, "2/2": 1}


def test_interval_resamples_tasks():
    """Every task passes all or nothing, half of each: a resample of tasks can hold only one
    kind, so the interval reaches both ends."""
    runs = [*rewards("a", 1, 1, 1), *rewards("b", 0, 0, 0)]
    result = model_result(NINE_B, runs)
    assert (result.low, result.high) == (0, 1)


def test_load_models_reads_one_folder_per_model(tmp_path: Path):
    for model, instance, reward in [(NINE_B, "a", 1), ("Qwen/Qwen3.5-35B-A3B-Base", "a", 0)]:
        folder = tmp_path / model.replace("/", "__")
        folder.mkdir(exist_ok=True)
        record = run(instance, 1, reward, model)
        (folder / f"{record.key.name}.json").write_text(record.model_dump_json())
    models = load_models(tmp_path)
    assert list(models) == ["Qwen/Qwen3.5-35B-A3B-Base", NINE_B]
    assert [r.record.reward for r in models[NINE_B] if r.record] == [1]
