# Harbor as the harness, with our own task builder

Tasks are packaged in Harbor format and run with `harbor run`. Harbor already handles containers, agents, trials and rewards, and its task format is what many RL-environment teams use. A custom harness would mean rewriting all of that for no research gain.

Harbor has no SWE-rebench adapter. Its `swegym` adapter is the closest match: same SWE-bench-shaped fields, prebuilt x86 images, and a `test.sh` built from `FAIL_TO_PASS` and `PASS_TO_PASS`. We do not fork the adapter. We write one small builder modeled on it, because each instance needs several grader conditions (baseline and H1–H4), and the adapter produces only one.

## Consequences

Harbor's default already copies tests in after the agent finishes. The baseline condition has to undo this on purpose (see ADR 0006).
