# Label agreement

A = `labels/human.jsonl`, B = `labels/opus_dev.jsonl`. 30 trajectories are labeled in both (0 only in A, 0 only in B, not compared).

| Field | Scored | Agree [95% Wilson interval] | Cohen's κ [95% bootstrap interval] |
|---|---|---|---|
| Failure class | 26 | 25/26 = 96% [81%, 99%] | 0.856 [0.519, 1.000] |
| Fooled reason | 9 | 6/9 = 67% | 0.438 [0.000, 1.000] |

Failure class: items either file calls `unclear` are left out (ADR 0003): A 2, B 2.
Fooled reason: scored where both files gave one; only A gave one: 0, only B gave one: 0.

## Failure classes the files disagree on

| A | B | Count |
|---|---|---|
| model_failure | unclear | 1 |
| task_underspecified | unclear | 1 |
| task_underspecified | upstream_tests_wrong | 1 |
| unclear | env_broken | 1 |
| unclear | model_failure | 1 |
