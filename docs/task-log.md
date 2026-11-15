# Task log

What made each instance easy or hard to turn into a Harbor task, and why candidates were rejected. Only observed facts go here.

## How a task is built

`make task ID=<instance_id>` reads the row from the pinned SWE-rebench parquet and writes `tasks/<instance_id lowercased>__baseline/` ([task_builder.py](../src/grader_proof/task_builder.py)). `make task ID=<instance_id> CONDITION=h1` writes `tasks/<instance_id lowercased>__h1/` instead. The table below is Baseline. H1 adds a copy of the test patch to `tests/` and restores the files it touches before the tests run ([ADR 0008](adr/0008-h1-restore-test-files.md)).

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

Fix in `task_builder.py`: the Dockerfile runs that command once at build time, after the test patch, in the `testbed` env. The tests stay offline at grade time. All 6 tasks were rebuilt and rerun after the change. The committed `12rambau__sepal_ui-411__baseline` was not rebuilt, so it differs from what the builder now writes.

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

- No candidate was rejected, so ranks 7 and later were not tried.
- The laptop oracle was not run for H1, H2 and H3, only on Actions (as the issue asks).
- Test names that `swegym` treats as problematic (truncated or non-ASCII ids) were not looked for.
