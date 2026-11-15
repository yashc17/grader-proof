# Task log

What made each instance easy or hard to turn into a Harbor task, and why candidates were rejected. Only observed facts go here.

## How a task is built

`make task ID=<instance_id>` reads the row from the pinned SWE-rebench parquet and writes `tasks/<instance_id lowercased>__baseline/` ([task_builder.py](../src/grader_proof/task_builder.py)). `make task ID=<instance_id> CONDITION=h1` writes `tasks/<instance_id lowercased>__h1/` instead. The table below is Baseline. H1 adds a copy of the test patch to `tests/` and restores the files it touches before the tests run ([ADR 0008](adr/0008-h1-restore-test-files.md)). `CONDITION=all` uses H3's workspace and runs H3's, H2's and H1's checks, in that order, before the tests.

| File | Content |
|---|---|
| `instruction.md` | `problem_statement`, with CRLF turned into LF |
| `environment/Dockerfile` | `FROM` the prebuilt image, then `git apply` of the test patch, so the upstream tests are in `/testbed` (Baseline, ADR 0006) |
| `tests/test.sh` | Activates the image's `testbed` conda env and runs `test_cmd` on every `FAIL_TO_PASS` and `PASS_TO_PASS` id, in place. Reward 1 if pytest exits 0, else 0 |
| `solution/solve.sh` | `git apply /solution/gold.patch` in `/testbed` |

Reward 1 means pytest selected exactly those ids and all passed. A missing id makes pytest exit non-zero, so a deleted test cannot pass.

To run a task (Harbor 0.26.0, installed with `uv tool install harbor==0.26.0`):

```
harbor run -p tasks/<task> -a oracle -o runs/<job> -n 1 -y   # expect reward 1
harbor run -p tasks/<task> -a nop    -o runs/<job> -n 1 -y   # expect reward 0
```

## 12rambau__sepal_ui-411

Image `swerebench/sweb.eval.x86_64.12rambau_1776_sepal_ui-411`. One `FAIL_TO_PASS` test, two `PASS_TO_PASS` tests, all in `tests/test_DatePicker.py`. The gold patch touches 2 files, one of them docs.

| Check (Colima + Rosetta, Apple M3) | Result |
|---|---|
| Oracle | reward 1.0, 3 of 3 tests pass, 1 min 9 s for the whole job |
| No-op agent | reward 0.0, `test_disable` fails with `assert None == True`, 50 s for the whole job |

Observed while converting:

- The image keeps its Python in a conda env at `/opt/conda/envs/testbed`. `pytest` is not in the `base` env, so `test.sh` must activate `testbed`. Harbor's `swegym` template uses `/opt/miniconda3`, which does not exist here.
- The image holds the repo at `base_commit` without the test patch. The Dockerfile applies it. The no-op run collects `test_disable`, which shows the test is in the workspace.
- The image's default command is `tail -f /dev/null` with working directory `/`, so the Dockerfile sets `WORKDIR /testbed`.
- The full suite does not load (`tests/test_gee.py` needs an Earth Engine login, issue #2). Running only the three listed ids avoids it. This is the grader's scope, not a workaround: `resolved` is defined on exactly these ids.
- Harbor 0.26.0 calls `docker compose`. Colima installs the `docker` CLI without the compose plugin, so the first run failed with `unknown flag: --project-name`. Fix: `brew install docker-compose` and link it into `~/.docker/cli-plugins/`.
- Not checked: the 3-of-3 oracle repeat, a GitHub Actions run, the test names that `swegym` treats as problematic (truncated or non-ASCII ids). This instance has none, so the builder does not handle them yet.

## Candidates 1-6 (issue #21)

Built from `results/candidates.csv` ranks 1-6, all four conditions each (`tasks/<id>__baseline|h1|h2|h3`). Laptop: Colima + Rosetta, Apple M3, 3 oracle runs per Baseline task. Actions: run [43658067682](https://github.com/yashc17/grader-proof/actions/runs/43658067682), 3 oracle runs per task and condition. All 6 candidates were kept. No test failed under the gold patch, so no test was dropped and every `FAIL_TO_PASS` count is unchanged.

| Rank | Instance | Image (`docker inspect`) | Tests (F2P + P2P) | Laptop oracle (s per run) | Laptop | Actions, baseline | Actions, H1 / H2 / H3 |
|---|---|---|---|---|---|---|---|
| 1 | `python-versioneer__python-versioneer-222` | 1.23 GB | 2 + 9 | 84, 56, 59 | 3 of 3 | 3 of 3 | 3 of 3 each |
| 2 | `addisonElliott__pyqt5ac-27` | 1.23 GB | 3 + 5 | 79, 60, 59 | 3 of 3 | 3 of 3 | 3 of 3 each |
| 3 | `altcha-org__altcha-lib-py-2` | 1.23 GB | 3 + 10 | 85, 61, 62 | 3 of 3 | 3 of 3 | 3 of 3 each |
| 4 | `vertexproject__synapse-294` | 1.37 GB | 2 + 82 | 92, 65, 68 | 3 of 3 | 3 of 3 | 3 of 3 each |
| 5 | `simonw__files-to-prompt-16` | 1.23 GB | 2 + 8 | 90, 66, 58 | 3 of 3 | 3 of 3 | 3 of 3 each |
| 6 | `David-Wobrock__sqlvalidator-40` | 1.23 GB | 4 + 235 | 64, 61, 64 | 3 of 3 | 3 of 3 | 3 of 3 each |

Times are whole-job seconds. The first run of each task is slower because it builds the image layers. Actions runs were not timed per run. For rank 1, `docker images` showed 4.62 GB unpacked; the unpacked size of the others was not recorded.

### What went wrong first: the package was not installed

The first laptop pass gave reward 0 for ranks 3, 5 and 6 (ranks 1, 2 and 4 passed). `pytest` stopped at collection with `ModuleNotFoundError: No module named 'altcha'` (`files_to_prompt` and `sqlvalidator` for the other two). For `sqlvalidator` the image holds the repo at `base_commit` and an `*.egg-info` folder, but `pip list` does not show the package, and plain `pytest` does not put `/testbed` on `sys.path`. Ranks 1, 2 and 4 passed without the install; why was not checked. SWE-bench's own eval script runs the instance's `install` command (`install_config.install`, for example `pip install -e .[dev]`) before every test run.

Fix in `task_builder.py`: the Dockerfile runs that command once at build time, after the test patch, in the `testbed` env. The tests stay offline at grade time. All 6 tasks were rebuilt and rerun after the change. `12rambau__sepal_ui-411__baseline` was not rebuilt; issue #22 removed it (see below).

### Per instance

| Instance | Easy | Hard |
|---|---|---|
| `python-versioneer-222` | 2 source files changed, no setup beyond the install step. | One test file, `test/git/test_git.py`. |
| `pyqt5ac-27` | 8 tests, fast. | The gold patch also changes CI files, `README.md`, `requirements.txt` and `setup.py`, and the test patch adds `.github/workflows/test_on_push.yml`. The test command is `pytest .`, so it collects the whole repo, not just the listed ids. |
| `altcha-lib-py-2` | One source file, one test file. | Needed the install step. |
| `synapse-294` | Passed on the first try. | Largest image (1.37 GB) and 82 P2P tests. Test files are inside the package (`synapse/tests/`). |
| `files-to-prompt-16` | 10 tests, one test file. | Needed the install step; the install uses an extra (`.[test]`) with quotes. |
| `sqlvalidator-40` | Source change is 2 files. | 239 test ids, so `test.sh` has a long argument list. Needed the install step. |

### H1, H2 and H3 on these tasks

Every condition accepted the gold patch in 3 of 3 runs for all 6 tasks. This does not check that a condition rejects a bad patch; #27 does the full false-negative check. H3 holds out one `FAIL_TO_PASS` test for ranks 1-5 and two for rank 6 (from `candidates.csv`).

### Not done

- No candidate of ranks 1-6 was rejected. Ranks 7 and later are in the next section.
- The laptop oracle was not run for H1, H2 and H3, only on Actions (as the issue asks).
- Test names that `swegym` treats as problematic (truncated or non-ASCII ids) were not looked for.

## Candidates 7-13 (issue #22)

Same method as #21, one candidate at a time. Each got 3 laptop oracle runs on Baseline; the five that passed were then built under H1, H2 and H3 and run 3 times each on Actions (run [43662353733](https://github.com/yashc17/grader-proof/actions/runs/43662353733), 24 task folders, all 3 of 3). The six that pass, with ranks 1-6, make **12 tasks**. The ranked 20 did not run out; ranks 14-20 were not tried. No test failed under the gold patch, so no test was dropped.

| Rank | Instance | Verdict | Image (compressed, `candidates.csv` / unpacked, `docker images`) | Tests (F2P + P2P) | Laptop oracle (s per run) | Actions, all four conditions |
|---|---|---|---|---|---|---|
| 7 | `jd__tenacity-479` | kept | 1.23 GB / 4.63 GB | 2 + 0 | 136, 70, 70 | 3 of 3 each |
| 8 | `peterbe__hashin-95` | kept | 1.24 GB / 4.59 GB | 2 + 38 | 115, 59, 62 | 3 of 3 each |
| 9 | `ftao__python-ifcfg-27` | kept | 1.24 GB / 4.59 GB | 2 + 12 | 116, 57, 59 | 3 of 3 each |
| 10 | `ska-sa__fakenewsredis-3` | kept | 1.24 GB / 4.60 GB | 16 + 766 | 166, 111, 112 | 3 of 3 each |
| 11 | `encode__httpx-222` | **rejected** | 1.39 GB / 5.05 GB | 8 ids, none failing | 129, 59, 65 (reward 0 each) | not run |
| 12 | `fox-it__dissect.cstruct-101` | kept | 1.24 GB / 4.65 GB | 6 + 45 | 123, 69, 72 | 3 of 3 each |
| 13 | `zopefoundation__zope.schema-39` | kept | 1.24 GB / 4.60 GB | 3 + 85 | 110, 62, 61 | 3 of 3 each |

Times are whole-job seconds; the first run builds the image layers. Pytest's own time: tenacity 0.08 s, hashin 2.4 s, ifcfg 0.3 s, fakenewsredis 56 s (782 tests), cstruct 0.2 s, zope.schema 0.2 s. H3 holds out 1, 1, 1, 8, 2 and 1 `FAIL_TO_PASS` functions for ranks 7, 8, 9, 10, 12 and 13.

### Why rank 11 was rejected

`httpx-222`: pytest passed all 8 listed ids in every run, but the exit code was 1 and the reward 0. The repo's pytest config requires 100% coverage (`FAIL Required test coverage of 100% not reached. Total coverage: 27.81%`). Running only the listed ids can never reach that, so the gold patch gets reward 0. No test was dropped; the gate is not a test. A fix would be to turn the gate off in `test.sh`, for example by passing `--cov-fail-under=0` when the option exists. That changes `test.sh` for every task, and #27 edits the builder too, so I did not do it. The rank was skipped and rank 13 was used. Selection effect: httpx was a `model_failure` instance, so the 12 hold 3 fewer of those than the ranked list (ranks 4 only; ranks 11 and 17 are not in).

### `12rambau__sepal_ui-411__baseline`

Removed, with its image. It is not one of the 12 and predates the install step and the history strip.

### What makes instances hard to convert

Observed over 13 candidates tried (12 built, 1 rejected):

- **The package is not installed in the image.** 3 of the first 6 failed at collection until the builder ran the instance's `install` command at build time. Ranks 7-13 needed no further change.
- **Repo-wide pytest settings.** `httpx-222` fails on a coverage gate. `pyqt5ac-27` runs `pytest .` and so collects the whole repo. Both come from the repo's config, not the test patch.
- **Test count and runtime.** `fakenewsredis-3` has 782 tests (56 s per run) and `sqlvalidator-40` 239 ids. Everything else is under 100 tests and under 3 s of pytest time.
- **Image size.** Images are 1.2-1.4 GB compressed and about 4.6-5.1 GB unpacked. The laptop needs one pull per task and about 2 minutes for the first run.
- **Not hard:** none of the 13 needed network access at test time, none had a flaky test across 3 runs, and none had test ids that needed escaping.
