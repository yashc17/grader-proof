# Codebook

This codebook turns [ADR 0003](adr/0003-failure-class-taxonomy.md) into decision rules for labeling unresolved trajectories. It records the rules actually applied to the 70 test and 30 dev labels in `labels/opus_test.jsonl` and `labels/opus_dev.jsonl`, which a Claude Opus 5.5 labeler wrote as set out in [ADR 0015](adr/0015-opus-test-labels.md). Terms follow [CONTEXT.md](../CONTEXT.md).

Every example below is a dev item, cited by its instance id. Test items stay held out, so none is named here, although several rules were first written while labeling them.

## Procedure for one trajectory

1. Read the issue as the agent saw it.
2. Read the `FAIL_TO_PASS` tests in the test patch and find which assertion the gold patch makes pass.
3. Read the agent's final patch, not what the agent says it did.
4. Decide which upstream test assertion the agent's patch fails, and why. The data has no evaluation logs, so this is done by reading code.
5. Read how the run ended: `submit`, the 100-turn limit, a stuck loop, or an infrastructure error.
6. Go through the failure classes in precedence order and stop at the first one that caused this failure.

## General rules

- **G1. A class fits only if it caused this failure.** An unclear issue does not make an item `task_underspecified` when the agent's patch would fail even under a clear issue, for example because it fixed the wrong code. Precedence only breaks ties between classes that each caused the failure.
- **G2. Judge the final patch.** Claims in the agent's summary, and scripts the agent wrote, are not evidence that the patch works.
- **G3. Repository conventions count as specification.** If the existing code, its tests or its documented behavior settle a detail that the issue leaves open, a careful engineer can infer that detail.

## env_broken

The environment stopped the agent before code quality mattered.

- **E1. Infrastructure ended the run or lost the patch.** Examples are an API timeout of the agent's model, a sandbox crash, or a patch-capture step that dropped the agent's edit.
  Example: `DRMacIver__shrinkray-7`. The agent made the gold patch's exact one-line change in `src/shrinkray/__main__.py` and viewed it in place before finishing, but the recorded patch contains only its scripts, so the fix never reached evaluation.
- **E2. Problems the agent worked around are not `env_broken`.** A missing package the agent installed, an install that shadows the source tree, or a test that hangs once does not stop the agent. If the patch is still wrong, the class is `model_failure`.

## task_underspecified

A careful engineer could not infer from the issue what the upstream tests check.

- **U1. The tests require a name, value format or exception type the issue never gives, and the repository does not settle it.**
  Example: `google__cloud-forensics-utils-330`. The agent validated CPU counts against the same list as the gold patch but raised the library's own `ResourceCreationError`; the test expects `ValueError`, and the issue names no exception.
- **U2. The issue allows two or more designs and the tests pin one the agent did not choose.**
  Example: `pytorch__ignite-703`. The issue asks for "the option to disable n_saved". The agent added `keep_all=True`; the test passes `n_saved=None`.
- **U3. The issue leaves a detail open, and the workspace's existing tests point the other way.** The agent keeps the old tests passing, and the new upstream tests expect the other choice.
  Example: `aiogram__aiogram-1250`. The agent forwards `message_thread_id` only when it is set, which keeps the existing `assert_awaited_with(action=..., chat_id=...)` passing. The new test requires `message_thread_id=None` to be passed explicitly.
- **U4. The issue contradicts itself on the point the tests check.** No dev item had this; it is listed because test items did.
- **U5. If the issue clearly states the behavior and the agent follows an old workspace test instead, the class is `model_failure`, not `task_underspecified`.**

## upstream_tests_wrong

The tests check something other than the issue, or reject a reasonable fix.

- **W1. A `FAIL_TO_PASS` test checks behavior the issue never asks for.** This happens when the fixing pull request bundled another change.
  Example: `IAMconsortium__nomenclature-391`. The agent added the line breaks the issue asks for, but two `FAIL_TO_PASS` tests check that ISO3-code errors are wrapped as `Collected 1 error:\n  1. ...`, which the issue never mentions.
- **W2. The issue states the behavior and the tests contradict it.**
- **W3. The tests reject a fix that does what the issue asks through a valid, documented mechanism, because they depend on an internal detail such as an interface method the mechanism does not require or the identity of a `NaN` object.**
- **W4. If the internal detail is an existing contract of the repository, such as one already asserted by its tests, and the agent changed it, the class is `model_failure` (G3).**

W2 and W3 have no dev example; both rules come from test items.

## model_failure

The task was fair and the agent's patch is wrong, incomplete, or missing.

- **M1. No source change.** The run ended in a `task_tracker` loop, at the turn limit, or after edits were reverted.
  Example: `cuenca-mx__cuenca-python-153`. The issue title says to remove the `err` field. The agent planned exactly that, then looped on `task_tracker view` until the loop detector stopped it.
- **M2. Wrong cause.** The agent changed code that is not where the bug is.
  Example: `vertexproject__synapse-294`. The agent wrapped the dataset loop in `list()`, but the error comes from the caching loop over `tufo[1].items()`.
- **M3. Partial fix.** The patch fixes part of what the issue states and misses the rest.
  Example: `feder-observatory__stellarphot-470`. The agent mapped only the `date-obs` lookup through `colname_map`; the unit checks still read the unmapped column names.
- **M4. An extra, unrequested change breaks the tests.**
  Example: `opsmill__infrahub-sdk-python-47`. The default-branch fallback is right, but the agent also renamed the public `branch_name` parameter to `branch`.
- **M5. The patch departs from what the issue, its own code snippet, or a repository convention says.**
  Example: `IAMconsortium__nomenclature-314`. The agent raised a hand-built pydantic `ValidationError` instead of the repository's own `ErrorCollector`, which it had read and called "the preferred approach".
- **M6. The patch fixes one caller and leaves the faulty function, often the one named in the traceback, unchanged.**
  Example: `burnash__gspread-1119`. The agent converted `None` to `[]` only in `get_all_records`; `numericise_all(ignore=None)` still fails.
- **M7. The agent saw its own tests fail, or ignored output that showed the bug, and submitted anyway.**
  Example: `airspeed-velocity__asv-704`. Its runs of `test/test_compare.py` exited 1 four times before it finished.

## unclear

Not enough evidence.

- **X1. The patch looks correct by reading, the agent's own runs passed, and nothing in the trajectory or the code explains why the upstream tests failed.** Without evaluation logs, guessing a cause would invent a result.
  Example: `idaholab__MontePy-538`. The agent removes the object from `data_inputs` after the failed first append, which should leave one copy as the test checks, and its own run showed four materials where four were expected.

## fooled_reason

This field is filled for self-check false positives only: trajectories whose patch passes the agent's own self-check (`pred_passes_gen_tests == 1`) but is not resolved. `check_fooled_reason` enforces this.

- **too_weak**: the self-check does not exercise the behavior that fails. This includes scripts that only print and never assert, checks that the code runs without crashing, and checks of the issue's example while the failing case differs.
  Example: `vertexproject__synapse-294`. The agent's scripts never enable caching, which the bug needs.
- **wrong_target**: the self-check tests a different code path from the one at fault. This usually follows an M2 misdiagnosis. No dev item had this reason.
- **mirrors_patch**: the self-check asserts what the patch does, not what is required. This includes editing existing tests to expect the patch's own call, and, for `task_underspecified` items, asserting the agent's own reading of the issue.
  Example: `zopefoundation__zope.component-55`. The agent's test asserts the double wrapping its patch adds, `LocatingUntrustedAdapterFactory` around `protectedFactory`.
- **other**: none of the above. The note says why. Cases seen: the self-check imported an installed copy of the package instead of the edited source, the patch is right and the upstream tests are wrong, or the cause of the failure is `unclear`.
  Example: `DigitalSlideArchive__tifftools-69`, labeled `unclear`.
