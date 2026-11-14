# Failure classes with a precedence order and a dev/test split

An unresolved trajectory gets exactly one failure class. When more than one fits, the first in this order wins:

1. `env_broken`: the environment stopped the agent before code quality mattered (missing dependency, broken install, the package does not import, network or timeout in the sandbox).
2. `task_underspecified`: a careful engineer could not infer from the issue what the upstream tests check (exact names, messages or formats the issue never mentions).
3. `upstream_tests_wrong`: the tests check something other than the issue, or reject a reasonable fix.
4. `model_failure`: the task was fair and the agent's patch is wrong, incomplete, or missing because it ran out of turns.
5. `unclear`: not enough evidence. Excluded from κ, and the count is reported.

For self-check false positives, a second field records why the self-check was fooled.

The precedence order makes labels mutually exclusive, which Cohen's κ needs. It also follows the order in which a reviewer rules causes out. Environment comes first because a broken environment hides everything else. The original four-class idea used "weak verifier", which mixed upstream tests with the agent's self-check. These are now separate: one is a class, the other is the second field.

Labels are split 30 dev / 70 test before labeling. Rules and prompts are tuned on dev only, so the reported κ is not fit to the labels it is scored on.
