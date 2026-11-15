"""Reads red-team trials (M3): the patch the agent left, and a compact record of each trial.

A red-team job is a Harbor `-o` directory run with `--artifact /testbed`, so each trial holds the
agent's final workspace under `artifacts/testbed`. `summarize` writes each trial's patch next to
its trajectory and one JSON file with tokens, cost, time and the projected cost of the M3 batch.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

ADAPTIVE_RUNS = 72  # 12 tasks x 2 conditions x 3 trials (design.md, M3)


class TrialRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: str
    trial: str
    agent: str
    agent_kwargs: dict[str, object]
    model: str
    reward: int | None
    turns: int
    prompt_tokens: int
    cached_prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    agent_seconds: float
    trial_seconds: float
    exception: str | None
    patch_files: list[str] | None = None


class PilotSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    instruction: str
    instruction_sha256: str
    trials: list[TrialRecord]
    mean_cost_usd: float
    projected_runs: int
    projected_cost_usd: float


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout


def base_commit(repo: Path) -> str:
    """The commit the agent started from.

    The task image expires the reflog, so a first entry, if there is one, records the agent's
    first move of HEAD (a commit or a checkout) and holds the starting commit as its old value.
    """
    log = repo / ".git" / "logs" / "HEAD"
    entries = log.read_text().splitlines() if log.exists() else []
    if not entries:
        return _git(repo, "rev-parse", "HEAD").strip()
    return entries[0].split()[0]


def agent_patch(repo: Path, tests_patch: Path) -> str:
    """The diff from the workspace the agent started with to the one it left.

    Baseline applies the upstream tests patch without committing it, so the start is the base
    commit plus that patch. Both trees are built in a throwaway index, so the repo's own index
    is left as it is. Ignored files (for example `__pycache__`) are not part of the patch.
    """
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(repo, "read-tree", base_commit(repo), env=env)
        _git(repo, "apply", "--cached", str(tests_patch.resolve()), env=env)
        start = _git(repo, "write-tree", env=env).strip()
        _git(repo, "add", "--all", env=env)
        end = _git(repo, "write-tree", env=env).strip()
    return _git(repo, "diff", "--binary", start, end)


def _seconds(timing: dict[str, str]) -> float:
    started = datetime.fromisoformat(timing["started_at"])
    finished = datetime.fromisoformat(timing["finished_at"])
    return (finished - started).total_seconds()


def read_trial(trial_dir: Path) -> TrialRecord:
    """Reads reward, token usage, cost and times from a Harbor trial's `result.json`."""
    result = json.loads((trial_dir / "result.json").read_text())
    usage = result["agent_result"]
    verifier = result["verifier_result"]
    exception = result["exception_info"]
    agent = result["config"]["agent"]
    return TrialRecord(
        task=result["task_name"],
        trial=result["trial_name"],
        agent=agent["name"],
        agent_kwargs=agent["kwargs"],
        model=result["agent_info"]["model_info"]["name"],
        reward=None if verifier is None else int(verifier["rewards"]["reward"]),
        turns=usage["metadata"]["n_episodes"],
        prompt_tokens=usage["n_input_tokens"],
        cached_prompt_tokens=usage["n_cache_tokens"],
        completion_tokens=usage["n_output_tokens"],
        cost_usd=usage["cost_usd"],
        agent_seconds=_seconds(result["agent_execution"]),
        trial_seconds=_seconds(result),
        exception=None if exception is None else exception["exception_type"],
    )


def changed_files(patch: str) -> list[str]:
    """The paths a `git diff` touches, from its `diff --git a/<path> b/<path>` headers."""
    return [
        line.split(" b/", 1)[1] for line in patch.splitlines() if line.startswith("diff --git ")
    ]


def summarize(job_dirs: list[Path], task_dir: Path, instruction: Path) -> PilotSummary:
    """Writes `patch.diff` into each trial that saved its workspace and summarizes the trials."""
    trials: list[TrialRecord] = []
    for trial_dir in sorted(p.parent for d in job_dirs for p in d.glob("*/result.json")):
        record = read_trial(trial_dir)
        workspace = trial_dir / "artifacts" / "testbed"
        if workspace.is_dir():
            patch = agent_patch(workspace, task_dir / "environment" / "upstream_tests.patch")
            (trial_dir / "patch.diff").write_text(patch)
            record = record.model_copy(update={"patch_files": changed_files(patch)})
        trials.append(record)
    if not trials:
        raise SystemExit(f"no trials under {[str(d) for d in job_dirs]}")
    mean_cost = sum(t.cost_usd for t in trials) / len(trials)
    return PilotSummary(
        instruction=instruction.as_posix(),
        instruction_sha256=hashlib.sha256(instruction.read_bytes()).hexdigest(),
        trials=trials,
        mean_cost_usd=mean_cost,
        projected_runs=ADAPTIVE_RUNS,
        projected_cost_usd=mean_cost * ADAPTIVE_RUNS,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="+", type=Path, help="Harbor job directories")
    parser.add_argument("--task", type=Path, required=True, help="the task folder that was run")
    parser.add_argument("--instruction", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.jobs, args.task, args.instruction)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(summary.model_dump_json(indent=2) + "\n")
    print(
        f"{len(summary.trials)} trials, mean ${summary.mean_cost_usd:.4f} per run, "
        f"projected ${summary.projected_cost_usd:.2f} for {summary.projected_runs} runs"
    )


if __name__ == "__main__":
    main()
