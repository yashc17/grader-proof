"""Reads the output of Harbor oracle runs and decides whether a task's oracle is reliable.

The oracle-check workflow runs the oracle `RUNS` times per task. Each run is one Harbor job
directory. This module turns those directories into one small JSON file per task, and turns a
folder of such files into a pass/fail table.
"""

import argparse
import sys
from pathlib import Path

from pydantic import BaseModel

RUNS = 3
FAILING_STATUSES = ("FAILED ", "ERROR ")


class RunResult(BaseModel):
    run: int
    reward: int | None
    failing_tests: list[str]


class TaskResult(BaseModel):
    task: str
    condition: str
    runs: list[RunResult]

    @property
    def passed(self) -> bool:
        """The oracle must get reward 1 in all `RUNS` runs."""
        return len(self.runs) == RUNS and all(r.reward == 1 for r in self.runs)

    @property
    def flaky(self) -> bool:
        """The runs disagree on the reward."""
        return len({r.reward for r in self.runs}) > 1


def split_task_name(name: str) -> tuple[str, str]:
    """Splits `<instance_id>__<condition>` at the last `__`."""
    task, separator, condition = name.rpartition("__")
    if not separator or not task:
        raise ValueError(f"task name {name!r} has no __<condition> suffix")
    return task, condition


def parse_failing_tests(pytest_output: str) -> list[str]:
    """Test ids from the `FAILED`/`ERROR` lines of `pytest -rA`, without the message."""
    failing: list[str] = []
    for line in pytest_output.splitlines():
        if line.startswith(FAILING_STATUSES):
            failing.append(line.split(" ", 1)[1].split(" - ", 1)[0])
    return failing


def read_run(job_dir: Path, run: int) -> RunResult:
    """Reads the reward and failing tests of the one trial under a Harbor `-o` directory."""
    reward_files = sorted(job_dir.glob("**/verifier/reward.txt"))
    if not reward_files:
        return RunResult(run=run, reward=None, failing_tests=[])
    verifier = reward_files[0].parent
    stdout = verifier / "test-stdout.txt"
    failing = parse_failing_tests(stdout.read_text()) if stdout.exists() else []
    return RunResult(
        run=run, reward=int(reward_files[0].read_text().strip()), failing_tests=failing
    )


def collect(task_name: str, runs_dir: Path, out_dir: Path) -> TaskResult:
    """Reads `runs_dir/run-1 … run-N` and writes `out_dir/<task_name>.json`."""
    task, condition = split_task_name(task_name)
    runs = [read_run(runs_dir / f"run-{i}", i) for i in range(1, RUNS + 1)]
    result = TaskResult(task=task, condition=condition, runs=runs)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{task_name}.json").write_text(result.model_dump_json(indent=2) + "\n")
    return result


def summarize(results_dir: Path) -> bool:
    """Prints one line per task and returns True if every oracle passed."""
    results = [
        TaskResult.model_validate_json(p.read_text()) for p in sorted(results_dir.rglob("*.json"))
    ]
    for r in results:
        rewards = " ".join(str(x.reward) for x in r.runs)
        status = "pass" if r.passed else "FLAKY" if r.flaky else "FAIL"
        print(f"{status:5} {r.task} [{r.condition}] rewards: {rewards}")
    return bool(results) and all(r.passed for r in results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect_cmd = commands.add_parser("collect", help="write the result file for one task")
    collect_cmd.add_argument("task_name")
    collect_cmd.add_argument("--runs-dir", type=Path, default=Path("runs"))
    collect_cmd.add_argument("--out-dir", type=Path, default=Path("oracle-check"))
    summarize_cmd = commands.add_parser("summarize", help="print a table of downloaded results")
    summarize_cmd.add_argument("results_dir", type=Path)
    args = parser.parse_args()

    if args.command == "collect":
        ok = collect(args.task_name, args.runs_dir, args.out_dir).passed
    else:
        ok = summarize(args.results_dir)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
