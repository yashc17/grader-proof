"""Runs the RQ4 batch (#33): each model on the All condition, 3 trials per task.

It reuses the red-team harness of #30 (`red_team_runs`): terminus-2 on Tinker, one trial at a
time, no network inside the container, one retry for an infrastructure failure and one image on
disk at a time. The agent gets the task's own instruction, with nothing appended. Each finished
trial gets a file in results/rq4_runs/<model>/, and a trial that has one is skipped, so a stopped
batch resumes where it left off.

Before each trial the spend so far, with truncated replies counted at their upper bound, plus the
most one trial of that model can cost, must stay within the budget given on the command line.
"""

import argparse
from datetime import datetime
from pathlib import Path

from grader_proof.llm import PRICES
from grader_proof.red_team_runs import (
    DISK_LIMIT_GB,
    LLM_KWARGS,
    MAX_TURNS,
    TASKS_DIR,
    TrialKey,
    colima_disk_used_gb,
    instances,
    load_runs,
    remove_images,
    run_trial,
    write_offline_task,
)

CONDITION = "all"
TRIALS = 3
RESULTS_DIR = Path("results/rq4_runs")
RUNS_DIR = Path("runs/rq4")


def model_dir_name(model: str) -> str:
    return model.replace("/", "__")


def max_call_usd(model: str) -> float:
    """One call with a prompt as long as the context limit, no cache hit and a full reply."""
    price = PRICES[model]
    context, reply = LLM_KWARGS["context_limit"], LLM_KWARGS["max_tokens"]
    return (int(context) * price.prefill + int(reply) * price.sample) / 1e6


def max_run_usd(model: str) -> float:
    return MAX_TURNS * max_call_usd(model)


def planned_trials(instance_ids: list[str], models: list[str]) -> list[tuple[str, TrialKey]]:
    """Every trial, grouped by instance so one task image is on disk at a time."""
    return [
        (model, TrialKey(instance=instance, condition=CONDITION, trial=trial))
        for instance in instance_ids
        for model in models
        for trial in range(1, TRIALS + 1)
    ]


def result_path(model: str, key: TrialKey) -> Path:
    return RESULTS_DIR / model_dir_name(model) / f"{key.name}.json"


def spent_upper_bound(models: list[str]) -> float:
    """Reported cost of every finished trial, with each truncated reply priced in full."""
    total = 0.0
    for model in models:
        for run in load_runs(RESULTS_DIR / model_dir_name(model)):
            if run.record is not None:
                total += run.record.cost_usd + run.record.truncated_replies * max_call_usd(model)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RQ4 batch on the All condition.")
    parser.add_argument("--models", nargs="+", required=True, help="Tinker model names")
    parser.add_argument("--budget", type=float, required=True, help="dollars approved")
    args = parser.parse_args()
    models: list[str] = args.models
    for model in models:
        if model not in PRICES:
            raise SystemExit(f"{model} has no price in llm.PRICES; add it before running")

    todo = [
        (model, key)
        for model, key in planned_trials(instances(TASKS_DIR), models)
        if not result_path(model, key).exists()
    ]
    for model in models:
        count = sum(m == model for m, _ in todo)
        print(
            f"{model}: {count} trials to run, at most ${max_run_usd(model):.2f} each "
            f"(${count * max_run_usd(model):.2f} in all)."
        )
    print(f"Spent so far: at most ${spent_upper_bound(models):.2f}. Budget ${args.budget:.2f}.")

    for instance in dict.fromkeys(key.instance for _, key in todo):
        since = datetime.now().astimezone()
        task = write_offline_task(TASKS_DIR / f"{instance}__{CONDITION}", RUNS_DIR / "tasks")
        for model, key in ((m, k) for m, k in todo if k.instance == instance):
            spent = spent_upper_bound(models)
            if spent + max_run_usd(model) > args.budget:
                print(f"STOP: spent at most ${spent:.2f}; one more trial could pass the budget.")
                remove_images(instance, since)
                return
            if (used := colima_disk_used_gb()) > DISK_LIMIT_GB:
                print(f"STOP: Colima disk {used:.1f} GB used, over {DISK_LIMIT_GB} GB.")
                return
            run = run_trial(key, task, RUNS_DIR / model_dir_name(model), model, instruction=None)
            path = result_path(model, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(run.model_dump_json(indent=2) + "\n")
            record = run.record
            print(
                f"{model} {key.name}: reward {None if record is None else record.reward}, "
                f"attempts {run.attempts}, ${0 if record is None else record.cost_usd:.4f}. "
                f"Spent at most ${spent_upper_bound(models):.2f}",
                flush=True,
            )
        remove_images(instance, since)


if __name__ == "__main__":
    main()
