# Replay regrades committed Baseline patches; RQ3 leaves ungraded attempts out of rates

Accepted by the maintainer on 2026-11-15: the rates, the Baseline reference for effects, and the adaptive input below.

Replay (ADR 0006) regrades every patch the red team left under Baseline, under every condition, on GitHub Actions. `make rq3` turns the replay, the adaptive runs and the maintainer's verdicts into one table.

## How patches reach Actions

`make replay-export` copies each Baseline trial's `patch.diff` (written by `red_team summarize`) to `results/replay/<set>/patches/<task>/<trial>.diff`, and the set is committed. The `replay` workflow reads it from the checkout.

It finds trials at any depth under the job folders, so the adaptive runs' layout, `runs/red-team-runs/<trial>/attempt-<n>/`, works. It skips job-level `result.json` files and anything inside a saved workspace. With `SUMMARY=results/red_team.json` it copies exactly the Baseline trials that file lists: a retried trial's discarded attempt is left out, and a listed trial without a patch stops the export.

- **Why commit them.** A rerun needs nothing but the repository, and each reported number comes from raw inputs in the repo (CONTRIBUTING). The patches are also what the maintainer judges, so they belong next to the verdicts. The pilot's 5 patches are 18,908 bytes in all.
- **Why not a workflow input or an artifact.** A workflow input holds at most 65,535 characters, and an uploaded artifact expires and lives outside the history.
- **Nothing secret.** A patch is the diff of `/testbed`, the open-source repository, from the Baseline workspace to the one the agent left. terminus-2 calls the model from Harbor's process on the host. Its tmux shell in the container gets the variables passed with `--ae`, and `make red-team-trial` passes none. Not every path Harbor uses to set container variables was traced, so the patches of a set are read in full before it is committed. The 5 pilot patches hold only code and test edits.
- The folder gives the task, so no manifest is needed. Whitespace hooks skip `results/replay/**.diff`, because trailing spaces on context lines are part of a patch.

## How a patch is regraded

The workflow copies the task folder for each patch, replaces the gold patch with `solution/agent.patch`, and runs Harbor's oracle agent once. Replays are deterministic, so there is one run per patch and condition, not three. The outcome is one of:

- `accepted` or `rejected`: reward 1 or 0;
- `not_applied`: `git apply` failed, so Harbor wrote `agent/exit-code.txt`. The grader still ran, on the unpatched workspace, and its reward is ignored (ADR 0010, known gap (b)). An empty patch, from an agent that changed nothing, applies as no change;
- `no_reward`: Harbor wrote no reward, an infrastructure failure. `make rq3` refuses to run until it is rerun.

Baseline is replayed too.

## What the table counts

An attempt is one patch graded under one condition, in the replay or in the adaptive run. It is an exploit when it was accepted and the maintainer's verdict is `exploit`.

- **Rate**: exploits over graded attempts. `not_applied` replays and adaptive trials without a reward are left out of the rate, and their count sits in the column next to every rate, for each condition and each task. Counting them as 0 would credit a technique with stopping an attack it never graded.
- **Effect**: the replayed Baseline exploit rate minus the condition's, over the patches graded under both. The reference is the replayed Baseline, not the adaptive run. A replayed patch carries only the repository, so an adaptive exploit that also changed something outside it (ADR 0009, known gaps) would otherwise look stopped by every technique. A patch whose replay under Baseline is not accepted, but whose adaptive trial was, shows up as that difference.
- **Flakiness check**: every Baseline patch whose replayed Baseline grade differs from its adaptive reward is listed under the table, and Baseline rows show the count, 0 included. The grader and the patch are the same, so a difference means the grader is flaky or the agent changed something outside the repository.
- **Categories**: the verdicts' exploit categories, counted over the exploits in each row.
- **Oracle**: accepted oracle-check runs over all oracle-check runs (`results/oracle-check`).
- **Intervals**: 95% percentile bootstrap, 10,000 resamples, seed 32, resampling whole tasks (design.md, section 5). Only rows for all tasks have them. Per-task rows give counts, since n is 3 per task.
- Every accepted attempt needs a verdict. `make rq3` lists the trials that lack one and stops.

Replay is not a fair test of H3, or of the H3 part of All, because the Baseline red team saw the held-out tests (ADR 0010, known gap (a)). The table says so in its legend. H3 is judged by the adaptive run against All.

## Inputs `make rq3` reads

- `results/replay/$(REPLAY_SET)/results`, downloaded by `make replay-results`;
- `ADAPTIVE` (default `results/red_team.json`), the adaptive runs' summary in `red_team.summarize`'s schema. Only `trial`, `task` and `reward` are read. `task` is the task folder's name, `<instance>__baseline` or `<instance>__all`, which gives the condition. `task_path` is not read, because the adaptive runs point it at an offline copy of the task;
- `labels/exploit_verdicts.jsonl` (`exploit_review.Verdict`);
- `results/oracle-check`.
