"""RQ4: are the hardened tasks discriminative? Pass rates per model on the All condition (#33).

Run with `make rq4` after `make rq4-runs`. It reads one folder of trial files per model under
results/rq4_runs/ and writes results/rq4.json: for each model, every task's pass rate (passing
trials over trials with a reward), their mean with a 95% bootstrap interval that resamples tasks
(design.md, section 7), and how many tasks reached each `passes/trials` count. Trials that ended
without a reward (an infrastructure failure after one retry) are left out and counted.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, ConfigDict

from grader_proof.red_team_runs import RunRecord, load_runs
from grader_proof.stats import bootstrap_ci

RUNS_DIR = Path("results/rq4_runs")
OUT = Path("results/rq4.json")
BOOTSTRAP_SEED = 0


class ModelResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    tasks: int
    trials: int
    no_reward: int
    mean_pass_rate: float
    low: float
    high: float
    per_task: dict[str, float]
    # Tasks by "passes/trials", in order of pass rate.
    distribution: dict[str, int]


def model_result(model: str, runs: Sequence[RunRecord]) -> ModelResult:
    rewards: dict[str, list[int]] = {}
    no_reward = 0
    for run in runs:
        reward = None if run.record is None else run.record.reward
        if reward is None:
            no_reward += 1
        rewards.setdefault(run.key.instance, [])
        if reward is not None:
            rewards[run.key.instance].append(reward)
    scored = {task: values for task, values in sorted(rewards.items()) if values}
    per_task = {task: mean(values) for task, values in scored.items()}
    rates = list(per_task.values())
    low, high = bootstrap_ci(rates, mean, seed=BOOTSTRAP_SEED)
    counts: dict[str, int] = {}
    for values in sorted(scored.values(), key=lambda v: (mean(v), len(v))):
        bucket = f"{sum(values)}/{len(values)}"
        counts[bucket] = counts.get(bucket, 0) + 1
    return ModelResult(
        model=model,
        tasks=len(per_task),
        trials=len(runs),
        no_reward=no_reward,
        mean_pass_rate=mean(rates),
        low=low,
        high=high,
        per_task=per_task,
        distribution=counts,
    )


def load_models(runs_dir: Path) -> dict[str, list[RunRecord]]:
    """Trial files by model, from one folder per model. The model name is read from the trials."""
    models: dict[str, list[RunRecord]] = {}
    folders = sorted(p for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.is_dir() else []
    for folder in folders:
        runs = load_runs(folder)
        names = {run.record.model for run in runs if run.record is not None}
        if len(names) > 1:
            raise ValueError(f"{folder} holds trials of more than one model: {sorted(names)}")
        if runs:
            models[names.pop() if names else folder.name] = runs
    return models


def main() -> None:
    parser = argparse.ArgumentParser(description="Pass rates per model on the All condition.")
    parser.add_argument("--runs", type=Path, default=RUNS_DIR)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    results = [model_result(model, runs) for model, runs in load_models(args.runs).items()]
    if not results:
        raise SystemExit(f"no trial files under {args.runs}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("[\n" + ",\n".join(r.model_dump_json(indent=1) for r in results) + "\n]\n")
    for r in results:
        print(
            f"{r.model}: mean pass rate {r.mean_pass_rate:.0%} [{r.low:.0%}, {r.high:.0%}] over "
            f"{r.tasks} tasks, {r.trials} trials ({r.no_reward} without a reward); "
            f"tasks by passes: {r.distribution}"
        )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
