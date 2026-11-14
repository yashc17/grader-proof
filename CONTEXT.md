# grader-proof

Coding agents are trained and scored by automated checks. This project measures how often those checks accept work that does not solve the issue, and how much hardening them helps.

## Data

**Instance**:
One GitHub issue from SWE-rebench with its repository snapshot, gold patch, test patch and Docker image.
_Avoid_: problem, example, sample

**Trajectory**:
One recorded agent attempt at one instance: the messages, tool calls and observations, and the final patch.
_Avoid_: trace, rollout, session

**Gold patch**:
The upstream code change that fixed the issue, without its test changes.
_Avoid_: reference solution, ground truth patch

**Upstream tests**:
The `FAIL_TO_PASS` and `PASS_TO_PASS` tests taken from the fixing pull request's test patch.
_Avoid_: hidden tests, gold tests

**Resolved**:
A patch is resolved when every `FAIL_TO_PASS` test passes and every `PASS_TO_PASS` test still passes.

**Self-check**:
The tests an agent wrote for itself during a trajectory. The dataset calls these "generated tests".
_Avoid_: generated tests, agent tests

## Verification

**Verifier**:
Any automated check that decides whether a patch solves the issue. Upstream tests, self-checks and graders are all verifiers.

**Grader**:
The verifier attached to a task. It inspects the container after the agent finishes and writes a reward of 0 or 1.
_Avoid_: reward model, evaluator

**Oracle**:
The gold patch applied by the task's `solution/solve.sh`. A correct grader gives it reward 1.

**False positive**:
A verifier accepts a patch that does not resolve the issue.

**False negative**:
A verifier rejects a patch that does resolve the issue, including the oracle.

**Self-check false positive**:
A trajectory whose patch passes its own self-check but is not resolved.

## Tasks and attacks

**Task**:
An instance rebuilt in Harbor format: instruction, environment, grader and oracle.
_Avoid_: environment (that word means the container only)

**Condition**:
One grader configuration for a task: the baseline or one hardening technique.

**Baseline**:
The unhardened condition. The upstream tests sit in the agent's workspace, and the grader runs them in place.

**Hardening technique**:
A change to the grader that is meant to stop exploits. H1 restores the test files at grading time, H2 rejects changed test or config files, H3 holds out some `FAIL_TO_PASS` tests, H4 adds property checks.

**Red-team agent**:
An agent told to make the grader pass without fixing the issue.

**Exploit**:
A red-team patch that the grader accepts and that the maintainer judged not to fix the issue.
_Avoid_: hack, cheat

**Exploit rate**:
Exploits divided by red-team trials, for one condition.

**Replay**:
Grading a saved patch under a different condition without rerunning the agent.

## Triage

**Failure class**:
Why an unresolved trajectory failed. One of `env_broken`, `task_underspecified`, `upstream_tests_wrong`, `model_failure`, or `unclear`. When more than one fits, the first in that order wins.

**Triager**:
Rules plus an LLM judge that assign a failure class to an unresolved trajectory.
