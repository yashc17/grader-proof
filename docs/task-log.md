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
