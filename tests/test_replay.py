import json
import subprocess
from pathlib import Path

import pytest

from grader_proof.replay import (
    AGENT_PATCH,
    ReplayResult,
    collect,
    export,
    listed_baseline_trials,
    prepare,
    read_outcome,
    render_solve_sh,
)


def red_team_trial(job: Path, trial: str, task: str, patch: str | None) -> None:
    directory = job / trial
    directory.mkdir(parents=True)
    result = {"task_name": task, "trial_name": trial, "verifier_result": {"rewards": {"reward": 0}}}
    (directory / "result.json").write_text(json.dumps(result))
    if patch is not None:
        (directory / "patch.diff").write_text(patch)


def test_export_copies_baseline_patches_into_one_folder_per_task(tmp_path: Path):
    job = tmp_path / "job"
    red_team_trial(job, "a__x1", "a__baseline", "diff A\n")
    red_team_trial(job, "a__x2", "a__all", "diff B\n")
    red_team_trial(job, "b__x3", "b__baseline", "")
    out = tmp_path / "set"
    assert export([job], out) == 2
    assert (out / "patches/a/a__x1.diff").read_text() == "diff A\n"
    assert (out / "patches/b/b__x3.diff").read_text() == ""
    assert not (out / "patches/a/a__x2.diff").exists()


def test_export_skips_and_names_trials_without_a_patch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    job = tmp_path / "job"
    red_team_trial(job, "a__x1", "a__baseline", None)
    assert export([job], tmp_path / "set") == 0
    assert "a__x1" in capsys.readouterr().out


def test_prepare_swaps_the_gold_patch_for_the_agent_patch(tmp_path: Path):
    task = tmp_path / "tasks/a__h1"
    for name, text in {
        "task.toml": "",
        "tests/test.sh": "grade",
        "solution/solve.sh": "gold",
        "solution/gold.patch": "gold patch",
    }.items():
        (task / name).parent.mkdir(parents=True, exist_ok=True)
        (task / name).write_text(text)
    patch = tmp_path / "x1.diff"
    patch.write_text("agent patch")

    copy = prepare(task, patch, tmp_path / "work/x1")
    assert copy == tmp_path / "work/x1/a__h1"
    assert (copy / "tests/test.sh").read_text() == "grade"
    assert sorted(p.name for p in (copy / "solution").iterdir()) == [AGENT_PATCH, "solve.sh"]
    assert (copy / "solution" / AGENT_PATCH).read_text() == "agent patch"
    assert (copy / "solution/solve.sh").stat().st_mode & 0o111
    assert (task / "solution/gold.patch").exists()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "testbed"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    return repo


def solve(repo: Path, patch: str) -> int:
    """Runs the replay solve.sh against `repo` with `patch` and returns its exit status."""
    patch_file = repo.parent / AGENT_PATCH
    patch_file.write_text(patch)
    script = render_solve_sh().replace("/testbed", str(repo))
    script = script.replace(f"/solution/{AGENT_PATCH}", str(patch_file))
    return subprocess.run(["bash", "-c", script], capture_output=True).returncode


EDIT = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"


def test_solve_sh_applies_the_agent_patch(repo: Path):
    assert solve(repo, EDIT) == 0
    assert (repo / "a.py").read_text() == "x = 2\n"


def test_solve_sh_accepts_an_empty_patch(repo: Path):
    """An agent that changed nothing leaves an empty patch, which `git apply` rejects."""
    assert solve(repo, "") == 0
    assert (repo / "a.py").read_text() == "x = 1\n"


def test_solve_sh_fails_when_the_patch_does_not_apply(repo: Path):
    (repo / "a.py").write_text("x = 3\n")
    assert solve(repo, EDIT) != 0


def harbor_trial(job: Path, reward: str | None, exit_code: str | None = None) -> None:
    trial = job / "trial-1"
    (trial / "verifier").mkdir(parents=True)
    (trial / "agent").mkdir()
    if reward is not None:
        (trial / "verifier/reward.txt").write_text(reward)
    if reward == "0":
        (trial / "verifier/test-stdout.txt").write_text("FAILED tests/t.py::test_a - boom\n")
    if exit_code is not None:
        (trial / "agent/exit-code.txt").write_text(exit_code)


@pytest.mark.parametrize(
    ("reward", "exit_code", "outcome"),
    [
        ("1", None, "accepted"),
        ("0", None, "rejected"),
        ("0", "1", "not_applied"),
        ("1", "1", "not_applied"),
        (None, None, "no_reward"),
    ],
)
def test_read_outcome(tmp_path: Path, reward: str | None, exit_code: str | None, outcome: str):
    harbor_trial(tmp_path, reward, exit_code)
    assert read_outcome(tmp_path)[0] == outcome


def test_read_outcome_keeps_the_failing_tests(tmp_path: Path):
    harbor_trial(tmp_path, "0")
    assert read_outcome(tmp_path) == ("rejected", ["tests/t.py::test_a"])


def test_collect_writes_one_result_per_patch(tmp_path: Path):
    patches = tmp_path / "set/patches/a"
    patches.mkdir(parents=True)
    for trial in ("x1", "x2"):
        (patches / f"{trial}.diff").write_text("")
    harbor_trial(tmp_path / "runs/x1", "1")
    harbor_trial(tmp_path / "runs/x2", "0", exit_code="1")

    results = collect("a__h3", tmp_path / "set", tmp_path / "runs", tmp_path / "out")
    assert results == [
        ReplayResult(task="a", trial="x1", condition="h3", outcome="accepted", failing_tests=[]),
        ReplayResult(
            task="a",
            trial="x2",
            condition="h3",
            outcome="not_applied",
            failing_tests=["tests/t.py::test_a"],
        ),
    ]
    saved = json.loads((tmp_path / "out/a__h3.json").read_text())
    assert [ReplayResult.model_validate(r) for r in saved] == results


def test_export_finds_trials_at_any_depth_but_not_jobs_or_saved_workspaces(tmp_path: Path):
    runs = tmp_path / "runs"
    red_team_trial(runs / "t1", "attempt-2", "a__baseline", "diff A\n")
    red_team_trial(runs / "t1/attempt-2/artifacts/testbed", "pkg", "a__baseline", "not a trial")
    (runs / "result.json").write_text(json.dumps({"n_total_trials": 1}))
    assert export([runs], tmp_path / "set") == 1
    assert (tmp_path / "set/patches/a/attempt-2.diff").read_text() == "diff A\n"


def test_export_keeps_only_the_listed_trials(tmp_path: Path):
    job = tmp_path / "job"
    red_team_trial(job, "x1", "a__baseline", "diff A\n")
    red_team_trial(job, "x2", "a__baseline", "diff B\n")
    assert export([job], tmp_path / "set", trials={"x2"}) == 1
    assert [p.name for p in (tmp_path / "set/patches/a").iterdir()] == ["x2.diff"]


def test_export_fails_when_a_listed_trial_has_no_patch(tmp_path: Path):
    job = tmp_path / "job"
    red_team_trial(job, "x1", "a__baseline", None)
    with pytest.raises(SystemExit, match="x1, x9"):
        export([job], tmp_path / "set", trials={"x1", "x9"})


def test_listed_baseline_trials_reads_the_red_team_summary(tmp_path: Path):
    summary = tmp_path / "red_team.json"
    trials = [
        {"trial": "x1", "task": "a__baseline"},
        {"trial": "x2", "task": "a__all"},
        {"trial": "x3", "task": "b__baseline"},
    ]
    summary.write_text(json.dumps({"trials": trials}))
    assert listed_baseline_trials(summary) == {"x1", "x3"}
