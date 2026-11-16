# Results draft

Draft write-up sections. Each one is written only from results that a `make` target rebuilt from real inputs.

## RQ1: why self-checks were fooled

From `make rq1` (`results/rq1.md`, `results/rq1.csv`), on the 70 test labels in `labels/opus_test.jsonl` (ADR 0015). 39 of the 70 unresolved trajectories have a self-check, and 29 passed it: these are the self-check false positives. Each has one `fooled_reason`; the intervals are Wilson 95%.

| Reason | Count | Share [95% interval] |
|---|---|---|
| `too_weak` | 14 | 48% [31%, 66%] |
| `mirrors_patch` | 7 | 24% [12%, 42%] |
| `other` | 5 | 17% [8%, 35%] |
| `wrong_target` | 3 | 10% [4%, 26%] |

With 29 items the intervals are wide. Only `too_weak` is clearly more common than `wrong_target`.

### too_weak: the self-check does not exercise the behavior that fails

- `Quantomatic__pyzx-150`: the check confirmed that a second `parse()` no longer adds gates, but never looked at the qubit count, which still carried over (2 instead of 1).
- `reframe-hpc__reframe-3328`: the agent ran `--duration` only with tests that always fail and checked for exit code 1, so it never tried a passing session that times out, the case the issue is about.
- `tox-dev__tox-772`: the scenarios used only env names that are not default factors, so they never reached the branch where the patch skips factor filtering for `py27`.

### mirrors_patch: the self-check asserts what the patch does

- `singingwolfboy__flask-dance-151`: the scripts assert the default scope is the two-URL list the agent chose, while the issue and the test want only the renamed `userinfo.profile` scope.
- `twisted__towncrier-594`: the agent edited the existing tests to expect `click.edit(..., filename='temp.rst')`, the call its own patch makes, instead of the `extension=` argument that click provides for this.
- `dwavesystems__dwave-system-373`: the agent edited the existing tests to expect its new call shape and kept `'-version'`, the `order_by` expression the issue says is wrong.

### other

- `Textualize__textual-4736`: the check imported a newer `textual` installed in site-packages, not the workspace source, so it reported no bug although no fix was made.
- `Unidata__MetPy-2653`: the patch gives the required NaN visibility, and the self-check tested it with a NaN-aware comparison; the upstream test compares tuples with `==`, which accepts only the `np.nan` object itself (labeled `upstream_tests_wrong`).
- `astanin__python-tabulate-243`: the self-check covered the empty and missing cells the issue asks about; the failing upstream test checks a thousands-separator change that the issue never mentions (labeled `upstream_tests_wrong`).

### wrong_target: the self-check tests a different code path

- `tox-dev__tox-2822`: the scripts check how `StrConvert.to_list` splits port lists, which already worked; the bug is INI factor filtering treating `8000:` as a factor.
- `alanmcruickshank__sqlfluff-262`: the scripts check tab-stop position arithmetic; the bug is an empty segment that the lexer emits after a fully trimmed tab.
- `facebookincubator__submitit-38`: the scripts probe pickling and watcher assignment; the bug is that `AutoExecutor.batch()` builds a base `Job` placeholder.

### Did the patch break a `PASS_TO_PASS` test or miss a `FAIL_TO_PASS` test?

This data cannot answer open question 6. The trajectories dataset records the upstream outcome only as `resolved`, `gen_tests_correct` and `pred_passes_gen_tests`, one value per trajectory, with no per-test results. Telling the two cases apart needs the upstream tests rerun on each sampled patch in its instance's image (`results/rq1.md`; design.md, open question 6).
