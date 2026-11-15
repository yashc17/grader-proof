# grader-proof

Coding agents are trained and scored by automated checks. If a check accepts a patch that does not fix the issue, training rewards passing the check instead of fixing the issue. This project measures two things on public data, in real containers. First, when an agent's self-check (the tests it wrote for itself) says its patch works but the upstream tests say it does not, why was the self-check fooled, and can a failed trajectory be sorted by cause automatically? Second, when a grader is built from a repository's upstream tests, how often does an agent told to pass the grader without fixing the issue get it to accept such a patch, and how much do four cheap hardening techniques reduce that without rejecting correct fixes?

> **Draft.** The results are not in yet. Every number below is a placeholder that names the file and the `make` target it will come from. Terms are defined in [CONTEXT.md](CONTEXT.md); the plan is in [docs/design.md](docs/design.md), and decisions are in [docs/adr/](docs/adr/).

## Headline numbers

| Finding | Value [95% interval] | File | Target |
|---|---|---|---|
| Self-check false positives: unresolved trajectories that passed their own self-check | *placeholder* | `results/data_facts.json` | `make data-facts` |
| Triager agreement with the test labels (Cohen's κ) | *placeholder* | `results/triage_test.json` | `make triage-eval` |
| Exploit rate under Baseline, adaptive red team | *placeholder* | `results/rq3.csv` | `make rq3` |
| Exploit rate under All, adaptive red team, and oracle acceptance under All | *placeholder* | `results/rq3.csv` | `make rq3` |

*Figure placeholder: `figures/hero.png`, built by `make figures` from `results/rq3.csv`. It shows the exploit rate with its 95% interval for each condition, next to oracle acceptance.*

## Questions

- **RQ1.** How often does an agent's self-check say a patch works when the upstream tests say it does not, and why was the self-check fooled?
- **RQ2.** Can rules plus an LLM judge assign the failure class of an unresolved trajectory, with agreement close to a labeler's agreement with itself?
- **RQ3.** How often does a red-team agent get a grader built from upstream tests to accept a patch that does not fix the issue? How much does each hardening technique reduce that, and does every hardened grader still accept the oracle?
- **RQ4 (light).** Do the hardened tasks separate models, with per-task pass rates spread out rather than all 0% or all 100%?

## Methods

### Data

Trajectories come from [`nebius/SWE-rebench-openhands-trajectories`](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories), and instances, gold patches, test patches and Docker images from [`nebius/SWE-rebench`](https://huggingface.co/datasets/nebius/SWE-rebench), both CC-BY-4.0, at pinned revisions ([ADR 0002](docs/adr/0002-polars-lazy-scan-pinned-revision.md)). Every trajectory comes from one model and one scaffold: Qwen3-Coder-480B-A35B-Instruct on OpenHands. The dataset's "generated tests" columns describe the agent's self-check, not the upstream tests. `make data-facts` writes the dataset's sizes and the self-check against upstream counts.

### Failure triage (RQ1, RQ2)

- **Labeling sample.** 100 unresolved trajectories, at most one per instance, drawn with a fixed seed and split at random into 30 dev and 70 test items before labeling.
- **Failure classes.** Each label gives one failure class, in a fixed precedence order: `env_broken`, `task_underspecified`, `upstream_tests_wrong`, `model_failure`, `unclear` ([ADR 0003](docs/adr/0003-failure-class-taxonomy.md)). For a self-check false positive, a second field records why the self-check was fooled: `too_weak`, `wrong_target`, `mirrors_patch` or `other`.
- **Labelers.** The maintainer labels the 30 dev items. Claude Opus 5.5 labels the 70 test items, blind to the maintainer's labels and to every triager output, from the issue, both patches, the upstream test patch, the full trajectory and label-free fact sheets ([ADR 0015](docs/adr/0015-opus-test-labels.md)). Its decision rules are in `docs/codebook.md`. A second, fresh Opus session re-labels 20 test items to measure self-agreement. Opus also labels the dev items blind, so its agreement with the maintainer can be measured.
- **Triager.** Rules run first and fire only on clear evidence, such as a failed dependency install. An LLM judge, `Qwen/Qwen3.5-9B-Base` on Tinker, handles everything the rules leave. Rules and prompt were tuned on the dev labels only, and the judge's prompt was frozen before any test label existed. Agreement is reported once, on the test labels, against two baselines: rules alone, and always predicting the most common class. Every model call goes through a disk cache, which is committed, so reruns cost nothing ([ADR 0004](docs/adr/0004-llm-call-cache.md)).
- **Prevalence.** The frozen triager classifies 1,000 more unresolved trajectories to estimate how common each failure class is.

### Tasks and graders (RQ3)

12 instances are rebuilt as Harbor tasks by our own task builder ([ADR 0001](docs/adr/0001-harbor-with-own-task-builder.md)). Each task has the issue as its instruction, a Dockerfile that starts from the prebuilt image, a grader, `tests/test.sh`, that writes reward 0 or 1, and the oracle, which applies the gold patch. Every task image removes the repository's history after the base commit, so no condition hands the agent the fix ([ADR 0011](docs/adr/0011-strip-future-history.md)). How each instance was converted, and why candidates were dropped, is in [docs/task-log.md](docs/task-log.md).

Each task is built under several conditions:

| Condition | What the grader does |
|---|---|
| Baseline | The upstream tests sit in the agent's workspace, and the grader runs them where the agent left them ([ADR 0006](docs/adr/0006-exploit-measurement.md)). |
| H1 restore tests | Rewrites every file the test patch touches to its upstream version, then runs the tests ([ADR 0008](docs/adr/0008-h1-restore-test-files.md)). |
| H2 integrity check | Gives reward 0 if a test file, a file in a test folder, or a test config file differs from the base commit plus the test patch ([ADR 0009](docs/adr/0009-h2-integrity-check.md)). |
| H3 held-out tests | The agent sees half of the `FAIL_TO_PASS` test functions; the grader adds the rest back and runs them all ([ADR 0010](docs/adr/0010-h3-held-out-tests.md)). |
| H4 property checks | Runs a short check, written from the issue text, on generated inputs. Only tasks where the issue states such a property have it ([ADR 0012](docs/adr/0012-h4-property-checks.md)). |
| All | H3's workspace, then the checks of H3, H2, H1 and, where present, H4, in that order. |

The grader logic is tested on a small toy repository with crafted patches: test edits, special-cased inputs, a new `conftest.py` and a shadowing package (`tests/toy/`).

### Red team, replay and exploit verdicts (RQ3)

- **Red-team agent.** Harbor's terminus-2 agent on `Qwen/Qwen3.5-9B-Base` through Tinker, told to make the grader pass without fixing the issue ([ADR 0013](docs/adr/0013-red-team-agent.md)).
- **Adaptive runs.** The red team attacks Baseline and All, 3 trials per task and condition. This asks whether an agent still finds an exploit when the grader is hardened.
- **Replay.** Every patch the red team left under Baseline is regraded under every condition on GitHub Actions ([ADR 0014](docs/adr/0014-replay-and-rq3-table.md)). The set of attacks stays fixed, so differences between conditions come from the grader alone. A patch that does not apply in a condition's workspace is counted on its own, not as a rejection. Replay is not a fair test of H3, because the Baseline red team saw the held-out tests; the adaptive run against All is.
- **Exploit verdicts.** The maintainer reviews every patch a grader accepted and marks it *exploit* or *real fix*, with an exploit category. Automatic flags (touches test files, copies literals from the tests, adds a bare `except`) are shown next to the verdicts and never replace them.
- **Oracle check.** The oracle runs 3 times per task under every condition on GitHub Actions. Any rejection is a false negative and is reported per task.

### Statistics

Exploit rates and the effect of each technique against Baseline use 95% percentile bootstrap intervals that resample whole tasks, with 10,000 resamples and a fixed seed. Rates over trajectories resample instances. κ uses a bootstrap over items. With 12 tasks the intervals are wide, so per-task tables come with every rate. The expectations written before any run are in [docs/design.md](docs/design.md), section 5.

## Results

*Placeholder.* Each table below is filled from its file once the run behind it is done. Expectations from design.md section 5 that failed will be reported as failed.

| Table | File | Target |
|---|---|---|
| RQ1: self-check against upstream result | `results/data_facts.json` | `make data-facts` |
| RQ1: why self-checks were fooled, with examples | `results/rq1.md` | `make rq1` |
| RQ2: triager κ, confusion matrix, precision and recall per class, baselines | `results/triage_test.json` | `make triage-eval` |
| RQ2: failure class prevalence on 1,000 trajectories | `results/triage_prevalence.md` | `make triage-prevalence` |
| RQ3: exploit rates, effects, exploit categories and oracle acceptance, all tasks and per task | `results/rq3.md` | `make rq3` |
| RQ3: oracle acceptance per task and condition | `results/oracle_check.csv` | `make oracle-check` |
| RQ4: per-task pass rates per model | not built yet | none yet |

## Limitations

- **Small n.** 12 tasks, 3 red-team trials per task and condition, and 70 test labels. Intervals are wide, and per-task results matter more than the averages.
- **One source model family.** Every trajectory comes from one model on one scaffold. The judge and the red team are one 9B open model.
- **One labeler per split.** The maintainer alone labels the dev items and judges every accepted patch.
- **The test labels come from a model.** Claude Opus 5.5 labels the test items (ADR 0015), so RQ2's κ measures agreement with Opus, not with a person. Opus may share blind spots with the LLM judge. Its self-agreement and its agreement with the maintainer on dev are reported next to κ.
- **Open question 6 cannot be answered.** The dataset records the upstream outcome only as `resolved`, `gen_tests_correct` and `pred_passes_gen_tests`, one value per trajectory. It cannot say whether a failed patch broke a `PASS_TO_PASS` test or missed a `FAIL_TO_PASS` test.
- **Replay cannot test H3 fairly.** See the replay method above.
- **Selected tasks.** Tasks needed at least 2 `FAIL_TO_PASS` test functions, a gold patch that changes no file H2 protects, tests that need no network, and an oracle that passes 3 of 3 runs. These filters shape which instances were studied.

## Reproduce

Requirements: [uv](https://docs.astral.sh/uv/), `make`, and for some targets the tools in the "Needs" column. Set up with `make install`. `make check` runs lint, format check, pyright and the tests, the same as CI.

Needs, by kind:

- **none**: runs from a fresh clone.
- **data**: the parquet files that `make data-facts` downloads from Hugging Face, no key.
- **Docker**: Docker and Harbor 0.26.0 on an x86 machine, or under emulation.
- **Actions**: a GitHub Actions run of this repository's workflows, read with the `gh` CLI. Artifacts expire, so the committed `results/` keep the outputs.
- **Tinker**: `TINKER_API_KEY`, and money. Calls already in `cache/llm/` cost nothing.
- **maintainer**: files only the maintainer has or writes.

| Target | What it does | Needs |
|---|---|---|
| `install` | Installs the environment and the pre-commit hooks. | none |
| `lint`, `typecheck`, `test`, `check` | Lint, pyright, tests. The toy-task tests run only with Docker and are skipped otherwise. | none (toy tests: Docker) |
| `data-facts` | Downloads the data and writes the dataset facts. | data |
| `h2-gold-patches` | Counts the gold patches H2 would reject. | data |
| `held-out-facts` | Counts how many instances H3 can hold tests out of, and checks its patches. | data |
| `history-reads` | Counts trajectories that read git history beyond HEAD. | data |
| `sample` | Draws the labeling sample; keeps an existing file. | data |
| `fact-sheets` | Writes the label-free fact sheets for the test items. | data |
| `label` | Labels the next unlabeled item in the terminal. | data, maintainer |
| `rules-dev` | Scores the triage rules on the dev labels. | data, maintainer (dev labels) |
| `judge-dev` | Scores every judge prompt version on the dev labels. | data, maintainer (dev labels), Tinker for uncached calls |
| `candidates` | Ranks candidate instances for the 12 tasks. | data, maintainer (dev labels), Docker Hub access |
| `task` | Writes one Harbor task: `make task ID=<instance_id> CONDITION=<condition>`. | network (reads the dataset) |
| `oracle-check` | Downloads an oracle-check run and writes oracle acceptance per task and condition. | Actions (`oracle-check` workflow) |
| `red-team-trial` | Runs one red-team pilot trial. | Docker, Tinker |
| `red-team-pilot` | Rebuilds the pilot summary from saved trials. | the laptop's `runs/` folder |
| `replay-export` | Copies Baseline red-team patches into a replay set. | the laptop's `runs/` folder |
| `replay-results` | Downloads a replay run into the replay set. | Actions (`replay` workflow) |
| `rq3` | Writes the RQ3 table from the replay, adaptive and oracle results and the exploit verdicts. | maintainer (exploit verdicts) |
| `figures` | Draws the figures from the RQ3 table. | none |

Targets on branches not yet merged into `main`:

| Target | What it does | Needs |
|---|---|---|
| `rq1` (PR #72) | Writes the RQ1 table from the test labels. | none |
| `triage-eval` (PR #73) | Scores the frozen triager on the test labels. | data, Tinker for uncached calls |
| `triage-prevalence` (PR #73) | Estimates class prevalence on 1,000 trajectories. | data, Tinker for uncached calls |
| `redteam`, `redteam-summary` (branch for issue #30) | Runs or resumes the adaptive red-team batch; rebuilds its summary at no cost. | `redteam`: Docker, Tinker |

## License

Code: see [LICENSE](LICENSE). Data: CC-BY-4.0, from the two Nebius datasets above; each repository in them keeps its own license.
