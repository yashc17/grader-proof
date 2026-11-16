"""Reads red-team trials (M3): the patch the agent left, and a compact record of each trial.

A red-team job is a Harbor `-o` directory run with `--artifact /testbed`, so each trial holds the
agent's final workspace under `artifacts/testbed`. `summarize` writes each trial's patch next to
its trajectory and one JSON file with tokens, cost, time, a one-line note on what the agent did,
and the projected cost of the M3 batch for each model and instruction.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter

ADAPTIVE_RUNS = 72  # 12 tasks x 2 conditions x 3 trials (design.md, M3)
TRUNCATED = "Response was truncated at max_tokens"


class TrialRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: str
    task_path: str
    trial: str
    instruction: str | None
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
    # Replies cut off at max_tokens. Harbor's Tinker backend raises before it records their
    # usage, so `cost_usd` leaves them out and is a lower bound when this is above 0.
    truncated_replies: int
    patch_files: list[str] | None = None
    activity: str | None = None


class Projection(BaseModel):
    """The cost of the 72 adaptive runs if every run cost what these trials did on average."""

    model_config = ConfigDict(frozen=True)

    model: str
    instruction: str | None
    agent_kwargs: dict[str, object]
    trials: int
    mean_cost_usd: float
    projected_runs: int
    projected_cost_usd: float


class PilotSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    instructions_sha256: dict[str, str]
    trials: list[TrialRecord]
    projections: list[Projection]


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
    usage = result.get("agent_result")
    execution = result.get("agent_execution")
    verifier = result["verifier_result"]
    exception = result["exception_info"]
    config = result["config"]
    instructions = config["extra_instruction_paths"]
    agent = config["agent"]
    log = trial_dir / "trial.log"
    log_lines = log.read_text().splitlines() if log.exists() else []
    return TrialRecord(
        task=result["task_name"],
        task_path=result["task_id"]["path"],
        trial=result["trial_name"],
        instruction=instructions[0] if instructions else None,
        agent=agent["name"],
        agent_kwargs=agent["kwargs"],
        model=result["agent_info"]["model_info"]["name"],
        reward=None if verifier is None else int(verifier["rewards"]["reward"]),
        turns=0 if usage is None else usage["metadata"]["n_episodes"],
        prompt_tokens=0 if usage is None else usage["n_input_tokens"],
        cached_prompt_tokens=0 if usage is None else usage["n_cache_tokens"],
        completion_tokens=0 if usage is None else usage["n_output_tokens"],
        cost_usd=0.0 if usage is None else usage["cost_usd"],
        agent_seconds=0.0 if execution is None else _seconds(execution),
        trial_seconds=_seconds(result),
        exception=None if exception is None else exception["exception_type"],
        truncated_replies=sum(TRUNCATED in line for line in log_lines),
    )


def changed_files(patch: str) -> list[str]:
    """The paths a `git diff` touches, from its `diff --git a/<path> b/<path>` headers."""
    return [
        line.split(" b/", 1)[1] for line in patch.splitlines() if line.startswith("diff --git ")
    ]


def read_trial_with_patch(trial_dir: Path) -> TrialRecord:
    """`read_trial`, plus the agent's patch written to `patch.diff` if the workspace was saved."""
    record = read_trial(trial_dir)
    workspace = trial_dir / "artifacts" / "testbed"
    if not workspace.is_dir():
        return record
    patch = agent_patch(workspace, Path(record.task_path) / "environment" / "upstream_tests.patch")
    (trial_dir / "patch.diff").write_text(patch)
    return record.model_copy(update={"patch_files": changed_files(patch)})


def project(trials: list[TrialRecord]) -> list[Projection]:
    """One projection per model, instruction and agent settings, in the order they first appear."""
    groups: dict[str, list[TrialRecord]] = {}
    for trial in trials:
        key = json.dumps([trial.model, trial.instruction, trial.agent_kwargs], sort_keys=True)
        groups.setdefault(key, []).append(trial)
    projections: list[Projection] = []
    for group in groups.values():
        first = group[0]
        mean_cost = sum(t.cost_usd for t in group) / len(group)
        projections.append(
            Projection(
                model=first.model,
                instruction=first.instruction,
                agent_kwargs=first.agent_kwargs,
                trials=len(group),
                mean_cost_usd=mean_cost,
                projected_runs=ADAPTIVE_RUNS,
                projected_cost_usd=mean_cost * ADAPTIVE_RUNS,
            )
        )
    return projections


def summarize(job_dirs: list[Path], notes: dict[str, str]) -> PilotSummary:
    """Writes `patch.diff` into each trial that saved its workspace and summarizes the trials.

    Task folders and instruction files are read at the paths the trials recorded, relative to
    the working directory. `notes` maps a trial name to a one-line note on what the agent did.
    """
    trials: list[TrialRecord] = []
    for trial_dir in sorted(p.parent for d in job_dirs for p in d.glob("*/result.json")):
        record = read_trial_with_patch(trial_dir)
        trials.append(record.model_copy(update={"activity": notes.get(record.trial)}))
    if not trials:
        raise SystemExit(f"no trials under {[str(d) for d in job_dirs]}")
    return trials_summary(trials)


def trials_summary(trials: list[TrialRecord]) -> PilotSummary:
    """The instructions' hashes, the trials and the projections, as one results file."""
    instructions = sorted({t.instruction for t in trials if t.instruction is not None})
    return PilotSummary(
        instructions_sha256={
            path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in instructions
        },
        trials=trials,
        projections=project(trials),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="+", type=Path, help="Harbor job directories")
    parser.add_argument("--notes", type=Path, help="JSON object: trial name -> one-line note")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    notes = TypeAdapter(dict[str, str]).validate_json(args.notes.read_text()) if args.notes else {}
    summary = summarize(args.jobs, notes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(summary.model_dump_json(indent=2) + "\n")
    print(f"{len(summary.trials)} trials, ${sum(t.cost_usd for t in summary.trials):.4f} in all")
    for p in summary.projections:
        print(
            f"{p.model}, {p.instruction}: {p.trials} trials, mean ${p.mean_cost_usd:.4f} per run, "
            f"${p.projected_cost_usd:.2f} for {p.projected_runs} runs"
        )
        print(f"  {json.dumps(p.agent_kwargs)}")


if __name__ == "__main__":
    main()
