"""Runs the M3 adaptive red-team batch (issue #30): 12 tasks x {Baseline, All} x 3 trials.

Trials run one at a time, one task at a time. Each attempt is one Harbor job under
`runs/red-team-runs/<trial>/attempt-<n>`, and each finished trial gets one compact result file,
`results/red_team_runs/<trial>.json`. A trial that already has a result file is skipped, so a
stopped batch resumes where it left off. A trial that ends without a reward (the container, the
agent setup or the grader did not run) is an infrastructure failure and is retried once.

Before each trial the spend so far, with truncated replies counted at their upper bound, plus the
most one trial can cost, must stay within the batch budget. The agent runs with no network inside
the container (ADR 0013): the trial uses a copy of the task folder with that one setting added.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter

from grader_proof.red_team import PilotSummary, TrialRecord, read_trial_with_patch, trials_summary

CONDITIONS = ("baseline", "all")
TRIALS = 3
ATTEMPTS = 2  # the first try and one retry

MODEL = "Qwen/Qwen3.5-9B-Base"
INSTRUCTION = Path("prompts/red-team-v2.md")
LLM_KWARGS = {
    "context_limit": 65536,
    "max_tokens": 4096,
    "renderer_name": "qwen3_5_disable_thinking",
}
MAX_TURNS = 40

# One 9B call with a full 64K prompt, no cache hit and a full reply, at Tinker list prices.
MAX_CALL_USD = (65_536 * 0.30 + 4_096 * 0.807) / 1_000_000
MAX_RUN_USD = MAX_TURNS * MAX_CALL_USD
PILOT_RUN_USD = 0.0621  # the pilot trial with these settings (results/red_team_pilot.json)
BUDGET_USD = 20.0  # approved for this batch
CAP_USD = 50.0  # Tinker credit for the whole project
DISK_LIMIT_GB = 50

TASKS_DIR = Path("tasks")
RUNS_DIR = Path("runs/red-team-runs")
RESULTS_DIR = Path("results/red_team_runs")
NOTES = Path("results/red_team_runs_notes.json")
SUMMARY = Path("results/red_team_runs.json")
ADAPTIVE = Path("results/red_team.json")  # same schema as results/red_team_pilot.json, read by #32


class TrialKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    instance: str
    condition: str
    trial: int

    @property
    def task(self) -> str:
        return f"{self.instance}__{self.condition}"

    @property
    def name(self) -> str:
        return f"{self.task}__{self.trial}"


class RunRecord(BaseModel):
    """One trial of the batch: the attempts it took and the last attempt's record."""

    model_config = ConfigDict(frozen=True)

    key: TrialKey
    attempts: int
    record: TrialRecord | None
    failure: str | None = None


class TrialRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial: str
    attempts: int
    reward: int | None
    patch_files: list[str] | None
    cost_usd: float | None
    truncated_replies: int | None
    activity: str | None


class RunsSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    planned: int
    done: int
    retried: int
    failed: int
    rewards: dict[str, dict[str, int]]
    spend_usd: float
    spend_upper_bound_usd: float
    budget_usd: float
    cap_usd: float
    trials: list[TrialRow]


def instances(tasks_dir: Path) -> list[str]:
    return sorted(p.name.removesuffix("__baseline") for p in tasks_dir.glob("*__baseline"))


def planned_trials(instance_ids: list[str]) -> list[TrialKey]:
    """Every trial of the batch, grouped by instance so one task image is on disk at a time."""
    return [
        TrialKey(instance=instance, condition=condition, trial=trial)
        for instance in instance_ids
        for condition in CONDITIONS
        for trial in range(1, TRIALS + 1)
    ]


def pending(planned: list[TrialKey], results_dir: Path) -> list[TrialKey]:
    return [key for key in planned if not (results_dir / f"{key.name}.json").exists()]


def is_infra_failure(record: TrialRecord | None) -> bool:
    """A trial that ended without a reward: Harbor wrote no result, or the grader never ran."""
    return record is None or record.reward is None


def spend(records: list[TrialRecord]) -> tuple[float, float]:
    """Reported cost, and an upper bound that prices each unrecorded truncated reply in full."""
    reported = sum(r.cost_usd for r in records)
    return reported, reported + sum(r.truncated_replies for r in records) * MAX_CALL_USD


def write_offline_task(task_dir: Path, copies_dir: Path) -> Path:
    """Copies a task folder and sets `network_mode = "no-network"` in its `[agent]` table."""
    copy = copies_dir / task_dir.name
    shutil.rmtree(copy, ignore_errors=True)
    shutil.copytree(task_dir, copy)
    config = copy / "task.toml"
    text = config.read_text()
    if "[agent]\n" not in text:
        raise ValueError(f"{config} has no [agent] table")
    config.write_text(text.replace("[agent]\n", '[agent]\nnetwork_mode = "no-network"\n', 1))
    return copy


def load_runs(results_dir: Path) -> list[RunRecord]:
    return [
        RunRecord.model_validate_json(p.read_text()) for p in sorted(results_dir.glob("*.json"))
    ]


def summarize_runs(
    results_dir: Path, planned: int, notes: dict[str, str] | None = None
) -> RunsSummary:
    notes = notes or {}
    runs = load_runs(results_dir)
    records = [run.record for run in runs if run.record is not None]
    rewards: dict[str, dict[str, int]] = {condition: {} for condition in CONDITIONS}
    for run in runs:
        if run.record is not None and run.record.reward is not None:
            counts = rewards[run.key.condition]
            counts[str(run.record.reward)] = counts.get(str(run.record.reward), 0) + 1
    reported, upper = spend(records)
    return RunsSummary(
        planned=planned,
        done=len(runs),
        retried=sum(run.attempts > 1 for run in runs),
        failed=sum(run.record is None or run.record.reward is None for run in runs),
        rewards=rewards,
        spend_usd=reported,
        spend_upper_bound_usd=upper,
        budget_usd=BUDGET_USD,
        cap_usd=CAP_USD,
        trials=[
            TrialRow(
                trial=run.key.name,
                attempts=run.attempts,
                reward=None if run.record is None else run.record.reward,
                patch_files=None if run.record is None else run.record.patch_files,
                cost_usd=None if run.record is None else run.record.cost_usd,
                truncated_replies=None if run.record is None else run.record.truncated_replies,
                activity=notes.get(run.key.name),
            )
            for run in runs
        ],
    )


def adaptive_summary(runs: list[RunRecord], notes: dict[str, str]) -> PilotSummary:
    """The trials that have a record, in the schema `red_team.summarize` writes."""
    return trials_summary(
        [
            run.record.model_copy(update={"activity": notes.get(run.key.name)})
            for run in runs
            if run.record is not None
        ]
    )


def harbor_command(
    task_dir: Path, job_dir: Path, model: str = MODEL, instruction: Path | None = INSTRUCTION
) -> list[str]:
    """terminus-2 on Tinker. With no instruction file, the agent gets the task's own instruction."""
    extra = ("--extra-instruction-path", str(instruction)) if instruction else ()
    return [
        *("uvx", "--from", "harbor[tinker]==0.26.0", "harbor", "run"),
        *("-p", str(task_dir), "-a", "terminus-2", "-m", model),
        *("--ak", "llm_backend=tinker", "--ak", f"max_turns={MAX_TURNS}"),
        *("--ak", "temperature=0.7", "--ak", f"llm_kwargs={json.dumps(LLM_KWARGS)}"),
        *extra,
        *("--artifact", "/testbed", "-o", str(job_dir), "-n", "1", "-y", "-q"),
    ]


def run_attempt(
    task_dir: Path, job_dir: Path, model: str = MODEL, instruction: Path | None = INSTRUCTION
) -> TrialRecord | None:
    """Runs one Harbor job and reads its trial, or returns None if Harbor wrote no trial result."""
    job_dir.mkdir(parents=True, exist_ok=True)
    with (job_dir / "harbor.log").open("w") as log:
        subprocess.run(
            harbor_command(task_dir, job_dir, model, instruction),
            env={**os.environ, "HARBOR_TELEMETRY": "0"},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    results = sorted(job_dir.glob("*/*/result.json"))
    return read_trial_with_patch(results[-1].parent) if results else None


def run_trial(
    key: TrialKey,
    task_dir: Path,
    runs_dir: Path = RUNS_DIR,
    model: str = MODEL,
    instruction: Path | None = INSTRUCTION,
) -> RunRecord:
    record: TrialRecord | None = None
    for attempt in range(1, ATTEMPTS + 1):
        job_dir = runs_dir / key.name / f"attempt-{attempt}"
        record = run_attempt(task_dir, job_dir, model, instruction)
        if not is_infra_failure(record):
            return RunRecord(key=key, attempts=attempt, record=record)
    failure = "no trial result" if record is None else f"no reward ({record.exception})"
    return RunRecord(key=key, attempts=ATTEMPTS, record=record, failure=failure)


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True).stdout


def remove_images(instance: str, since: datetime) -> None:
    """Removes the task's base image, Harbor's built task images and build layers since `since`.

    Harbor tags a built task image `hb__<id>`, or `<trial>__env-main` when the egress-control
    sidecar is on. The sidecar's own image (`harbor-prebuilt:…`) is kept for the next task.
    """
    dockerfile = TASKS_DIR / f"{instance}__baseline" / "environment" / "Dockerfile"
    base = dockerfile.read_text().split()[1]
    built = [
        reference
        for reference in _docker("images", "--format", "{{.Repository}}:{{.Tag}}").split()
        if reference.startswith("hb__") or reference.split(":")[0].endswith("__env-main")
    ]
    layers = [
        image_id
        for image_id, created in (
            line.split(" ", 1)
            for line in _docker(
                "images", "-a", "--filter", "dangling=true", "--format", "{{.ID}} {{.CreatedAt}}"
            ).splitlines()
        )
        if datetime.strptime(" ".join(created.split()[:3]), "%Y-%m-%d %H:%M:%S %z") >= since
    ]
    for image in (base, *built, *reversed(layers)):
        _docker("rmi", image)


def colima_disk_used_gb() -> float:
    out = subprocess.run(
        ["colima", "ssh", "--", "df", "--output=used", "-B1", "/mnt/lima-colima"],
        capture_output=True,
        text=True,
    ).stdout
    return int(out.split()[-1]) / 1e9


def write_summary(planned: int) -> RunsSummary:
    notes = TypeAdapter(dict[str, str]).validate_json(NOTES.read_text()) if NOTES.exists() else {}
    summary = summarize_runs(RESULTS_DIR, planned, notes)
    SUMMARY.write_text(summary.model_dump_json(indent=2) + "\n")
    if runs := load_runs(RESULTS_DIR):
        ADAPTIVE.write_text(adaptive_summary(runs, notes).model_dump_json(indent=2) + "\n")
    return summary


def main() -> None:
    planned = planned_trials(instances(TASKS_DIR))
    if "--summary-only" in sys.argv:
        write_summary(len(planned))
        return
    todo = pending(planned, RESULTS_DIR)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _, spent = spend([run.record for run in load_runs(RESULTS_DIR) if run.record is not None])
    print(
        f"{len(todo)} of {len(planned)} trials to run. Estimate ${len(todo) * PILOT_RUN_USD:.2f} "
        f"at ${PILOT_RUN_USD} per trial, at most ${len(todo) * MAX_RUN_USD:.2f}. "
        f"Spent so far: at most ${spent:.2f}. Budget ${BUDGET_USD:.0f}.",
        flush=True,
    )
    for instance in dict.fromkeys(key.instance for key in todo):
        since = datetime.now().astimezone()
        copies = {
            condition: write_offline_task(
                TASKS_DIR / f"{instance}__{condition}", RUNS_DIR / "tasks"
            )
            for condition in CONDITIONS
        }
        for key in (k for k in todo if k.instance == instance):
            _, spent = spend(
                [run.record for run in load_runs(RESULTS_DIR) if run.record is not None]
            )
            if spent + MAX_RUN_USD > BUDGET_USD:
                print(f"STOP: spent at most ${spent:.2f}; one more trial could pass the budget.")
                remove_images(instance, since)
                return
            if (used := colima_disk_used_gb()) > DISK_LIMIT_GB:
                print(f"STOP: Colima disk {used:.1f} GB used, over {DISK_LIMIT_GB} GB.")
                return
            run = run_trial(key, copies[key.condition])
            (RESULTS_DIR / f"{key.name}.json").write_text(run.model_dump_json(indent=2) + "\n")
            summary = write_summary(len(planned))
            record = run.record
            print(
                f"{key.name}: reward {None if record is None else record.reward}, "
                f"attempts {run.attempts}, ${0 if record is None else record.cost_usd:.4f}, "
                f"files {None if record is None else record.patch_files}. "
                f"Done {summary.done}/{summary.planned}, spent ${summary.spend_usd:.2f} "
                f"(at most ${summary.spend_upper_bound_usd:.2f})",
                flush=True,
            )
        remove_images(instance, since)
    write_summary(len(planned))


if __name__ == "__main__":
    main()
