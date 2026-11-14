# Workflow

Every unit of work starts as a GitHub issue. The issue states what to build and how we will know it is done.

**Branches.** One branch per issue, named `m<milestone>/<issue>-<slug>`, for example `m1/12-load-trajectories`.

**Commits.** Small and atomic, in [Conventional Commits](https://www.conventionalcommits.org/) form: `feat(triage): …`, `fix(tasks): …`, `test: …`, `docs: …`, `build: …`, `ci: …`. Each commit passes `make check`. History is never rewritten on `main`.

**Pull requests.** One PR per issue, small enough to review in 15 minutes. The body says what changed, why, and how it was verified, and ends with `Closes #<issue>`. CI must pass before merge.

**Tests.** Test-first for parsing, metrics (κ, intervals, exploit rates) and grader logic. Glue code and plotting are checked by running them, not by unit tests.

**Bugs.** A real bug gets its own issue (`type:bug`) describing how it was found, then a fix PR with a test that fails before the fix.

**Experiments.** Each reported number comes from a `make` target that rebuilds it from raw inputs. LLM calls are cached on disk, so rerunning a target costs nothing.

**Checks.** `make install` sets up the environment and the pre-commit hooks. `make check` runs lint, format check, pyright and pytest, the same as CI.

**Labels.** `type:*` (feat, bug, docs, experiment), `area:*` (triage, tasks, grading, writeup), `size:*` (S under 2 hours, M one evening, L split it), and `needs:human` for work only the maintainer can do, such as labeling.
