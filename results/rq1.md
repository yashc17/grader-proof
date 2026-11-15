# RQ1: why self-checks were fooled

From `labels/opus_test.jsonl`: 70 labeled unresolved trajectories, 39 with a self-check, 29 that passed it (self-check false positives).

| Reason | What it means | Count | Share [95% Wilson interval] |
|---|---|---|---|
| too_weak | the self-check does not exercise the behavior the issue describes | 14 | 48% [31%, 66%] |
| wrong_target | the self-check tests something other than the issue | 3 | 10% [4%, 26%] |
| mirrors_patch | the self-check asserts what the patch does, not what is required | 7 | 24% [12%, 42%] |
| other | none of the above; say why in the note | 5 | 17% [8%, 35%] |

## Examples (labelers' notes, up to 3 per reason)

### too_weak

- chatcmpl-171ec0401856599cfcbdedb1f2089be9: No source change: after choosing a missing_values='raise'|'ignore' design, the agent looped on task_tracker view until AgentStuckInLoopError.
- chatcmpl-17abfb91b02e6b517ff5a8e0e7a042e1: Run ended at message 43 on 'litellm.Timeout: APITimeoutError' before any source edit; the sandbox also lacks the gi module, so mopidy_local.commands does not import.
- chatcmpl-189d69fe8da46cd4487bdcc6b526d2b0: Applies factors to substituted {[testenv]deps} only for env names outside tox's default_factors, so [testenv:py27] still gets the raw 'coverage: coverage' line; the run hit 100 turns.

### wrong_target

- chatcmpl-11d2770e87e9045c90559c2a2e2be66a: Blamed unpickling overwriting 'watcher' and filtered it in Job.__setstate__; the real cause is batch() building a base Job shell because AutoExecutor.job_class is Job, and the run hit 100 turns.
- chatcmpl-6b98b124d754dd4126aa33c1cd615eaf: Misdiagnosed as tab-stop column counting and edited advance_by; the real bug is _trim emitting an empty segment after a fully trimmed '\t'; ran out of turns mid-edit.
- chatcmpl-e9499bc22428850027cc7973b7e015f1: Cause is factor expansion treating '8000:' as a factor filter in ini/factor.py; the agent only normalized line endings in StrConvert.to_list and hit 100 turns.

### mirrors_patch

- chatcmpl-0e84b0ea6e868369bc1f90f3386c92ed: Moved external_building_id to building_address but reversed the lookup order, so SendingSystemIdentifierValue now beats extension/HESExternalID, against the documented preference; the agent swapped it to fit its own test.
- chatcmpl-3409e92a7c0fd6b2db17f20f56b16d2d: Default scope set to profile plus email URLs; the issue asks to rename the existing ['profile'] default, and the test expects only the userinfo.profile URL.
- chatcmpl-4350fb4c2b168ac10adad2f5ae992ec6: Tests require REST schema changes the issue never mentions: run_elements/samples endpoints, 'aggregated.*' field paths, an 'RE Coverage' field and 'Required Yield (Gb)' / 'Coverage (X)' UDFs.

### other

- chatcmpl-24146deb26ccc5857c2d99f7bff4d782: Agent's fix gives visibility NaN as required, but its NaN passes through units.Quantity(...).m_as('meter') and is a new float, so the namedtuple == check (which relies on np.nan identity) fails.
- chatcmpl-39aa2d241afbfb2c4e0c9d19bbc023c3: Agent's empty-string handling matches the gold logic in _type and _format, but F2P test_floatfmt_thousands checks parsing '1,234.56' as a float, a thousands-separator feature the issue never mentions.
- chatcmpl-7507a2410bdc4c56873dfdfa8cef3114: hy_eval now runs both eval steps in one copied namespace, which by reading should also print 'fizbing' for the new test, and tests/test_bin.py passed in the agent's run; the data has no eval log showing what failed, so why its passing self-check missed the failure is also unknown.

## Broke a PASS_TO_PASS test or missed a FAIL_TO_PASS test?

The data cannot say. The trajectories dataset records the upstream outcome only as
`resolved`, `gen_tests_correct` and `pred_passes_gen_tests`, one value per trajectory, with no
per-test results. Telling the two apart needs the upstream tests rerun on each sampled patch in
its instance's image (design.md, open question 6).
