# Results draft

Draft write-up sections. Each one is written only from results that a `make` target rebuilt from real inputs.

## RQ1: why self-checks were fooled

Not written yet: it waits for the Opus test labels (`labels/opus_test.jsonl`, ADR 0015). It will hold:

- the table from `make rq1` (`results/rq1.md`): each `fooled_reason` with its count and share of the labeled self-check false positives;
- 2–3 short real examples per reason, taken from the labels' notes and checked against the trajectories;
- why the data cannot say whether a patch broke a `PASS_TO_PASS` test or missed a `FAIL_TO_PASS` test (open question 6): only `resolved`, `gen_tests_correct` and `pred_passes_gen_tests` exist, with no per-test results.
