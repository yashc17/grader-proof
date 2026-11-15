"""Replay (M3): regrades saved Baseline red-team patches under every condition on Actions.

A replay set is a folder, `results/replay/<set>/`:

- `patches/<task>/<trial>.diff`: the patch each Baseline red-team trial left (`patch.diff`,
  written by `red_team summarize`), copied there by `export`. They are committed, so the replay
  workflow and anyone rerunning it need nothing but the repository.
- `results/`: one JSON file per task folder with the outcome of each patch, written by `collect`
  on Actions and downloaded by `make replay-results`.

A patch is the diff from the Baseline workspace to the one the agent left. H1, H2 and H4 share
that workspace. H3 and All show only the visible tests, so a patch that edits a held-out test
does not apply there. That is its own outcome, not a rejection (ADR 0010, known gap (b)).
"""

import argparse
import json
import shutil
from collections.abc import Collection, Iterator, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from grader_proof.oracle_check import read_run, split_task_name

Outcome = Literal["accepted", "rejected", "not_applied", "no_reward"]
AGENT_PATCH = "agent.patch"


class ReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: str
    trial: str
    condition: str
    outcome: Outcome
    failing_tests: list[str]


RESULTS = TypeAdapter(list[ReplayResult])


def _trial_results(job_dirs: Sequence[Path]) -> Iterator[dict[str, Any]]:
    """The `result.json` of every Harbor trial under `job_dirs`, at any depth.

    Job-level `result.json` files name no trial, and files inside a saved workspace
    (`artifacts/`) belong to the repository, so both are skipped.
    """
    for job_dir in job_dirs:
        for path in sorted(job_dir.rglob("result.json")):
            if "artifacts" in path.relative_to(job_dir).parts:
                continue
            result = json.loads(path.read_text())
            if "trial_name" in result:
                yield {**result, "directory": path.parent}


def listed_baseline_trials(summary: Path) -> set[str]:
    """The Baseline trials a `red_team summarize` file lists."""
    trials = json.loads(summary.read_text())["trials"]
    return {t["trial"] for t in trials if split_task_name(t["task"])[1] == "baseline"}


def export(job_dirs: Sequence[Path], set_dir: Path, trials: Collection[str] | None = None) -> int:
    """Copies each Baseline trial's `patch.diff` into `set_dir/patches/<task>/<trial>.diff`.

    Returns the number copied. Without `trials`, a trial without a patch (its workspace was not
    saved) is named and skipped. With `trials`, only those are copied, and any of them without a
    patch is an error, so a replay set never silently drops an attack.
    """
    copied: set[str] = set()
    for result in _trial_results(job_dirs):
        trial = result["trial_name"]
        task, condition = split_task_name(result["task_name"])
        if condition != "baseline" or (trials is not None and trial not in trials):
            continue
        patch = result["directory"] / "patch.diff"
        if not patch.exists():
            print(f"skipped {trial}: no patch.diff")
            continue
        if trial in copied:
            raise SystemExit(f"{trial} has more than one result under {list(map(str, job_dirs))}")
        target = set_dir / "patches" / task / f"{trial}.diff"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(patch, target)
        copied.add(trial)
    if trials is not None and (missing := sorted(set(trials) - copied)):
        raise SystemExit(f"listed trials without a patch.diff: {', '.join(missing)}")
    return len(copied)


def render_solve_sh() -> str:
    """Applies the agent's patch. If it does not apply, the script fails, Harbor's oracle agent
    writes `agent/exit-code.txt`, and the grader still runs on the unpatched workspace."""
    return f"""#!/bin/bash
set -euo pipefail

cd /testbed
# An agent that changed nothing leaves an empty patch, which git apply rejects.
if [ -s /solution/{AGENT_PATCH} ]; then
    git apply /solution/{AGENT_PATCH}
fi
"""


def prepare(task_dir: Path, patch: Path, work_dir: Path) -> Path:
    """Copies a task folder into `work_dir` with the agent's patch in place of the gold patch.

    The copy keeps the folder's name, which Harbor uses for the image name, so every patch of one
    task folder reuses the same image.
    """
    task = work_dir / task_dir.name
    shutil.copytree(task_dir, task)
    shutil.rmtree(task / "solution")
    (task / "solution").mkdir()
    shutil.copyfile(patch, task / "solution" / AGENT_PATCH)
    solve = task / "solution/solve.sh"
    solve.write_text(render_solve_sh())
    solve.chmod(0o755)
    return task


def read_outcome(job_dir: Path) -> tuple[Outcome, list[str]]:
    """The outcome of one replay under a Harbor `-o` directory, and the tests that failed."""
    run = read_run(job_dir, run=1)
    if any(job_dir.glob("**/agent/exit-code.txt")):
        return "not_applied", run.failing_tests
    if run.reward is None:
        return "no_reward", run.failing_tests
    return ("accepted" if run.reward == 1 else "rejected"), run.failing_tests


def collect(task_name: str, set_dir: Path, runs_dir: Path, out_dir: Path) -> list[ReplayResult]:
    """Reads `runs_dir/<trial>` for each patch of the task and writes `out_dir/<task_name>.json`."""
    task, condition = split_task_name(task_name)
    results: list[ReplayResult] = []
    for patch in sorted((set_dir / "patches" / task).glob("*.diff")):
        outcome, failing = read_outcome(runs_dir / patch.stem)
        results.append(
            ReplayResult(
                task=task,
                trial=patch.stem,
                condition=condition,
                outcome=outcome,
                failing_tests=failing,
            )
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{task_name}.json").write_bytes(RESULTS.dump_json(results, indent=2) + b"\n")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export_cmd = commands.add_parser("export", help="copy Baseline patches into a replay set")
    export_cmd.add_argument("jobs", nargs="+", type=Path, help="Harbor job directories")
    export_cmd.add_argument("--set", type=Path, required=True, dest="set_dir")
    export_cmd.add_argument(
        "--summary", type=Path, help="red_team summarize file: copy only its Baseline trials"
    )
    prepare_cmd = commands.add_parser("prepare", help="copy a task with an agent patch")
    prepare_cmd.add_argument("task_dir", type=Path)
    prepare_cmd.add_argument("patch", type=Path)
    prepare_cmd.add_argument("work_dir", type=Path)
    collect_cmd = commands.add_parser("collect", help="write the outcomes for one task folder")
    collect_cmd.add_argument("task_name")
    collect_cmd.add_argument("--set", type=Path, required=True, dest="set_dir")
    collect_cmd.add_argument("--runs-dir", type=Path, default=Path("runs"))
    collect_cmd.add_argument("--out-dir", type=Path, default=Path("replay"))
    args = parser.parse_args()

    if args.command == "export":
        trials = listed_baseline_trials(args.summary) if args.summary else None
        print(f"copied {export(args.jobs, args.set_dir, trials)} patches to {args.set_dir}")
    elif args.command == "prepare":
        print(prepare(args.task_dir, args.patch, args.work_dir))
    else:
        for r in collect(args.task_name, args.set_dir, args.runs_dir, args.out_dir):
            print(f"{r.outcome:11} {r.trial} [{r.condition}]")


if __name__ == "__main__":
    main()
