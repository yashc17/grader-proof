# Label agreement

A = `labels/opus_test.jsonl`, B = `labels/opus_test_relabel.jsonl`. 20 trajectories are labeled in both (50 only in A, 0 only in B, not compared).

| Field | Scored | Agree [95% Wilson interval] | Cohen's κ [95% bootstrap interval] |
|---|---|---|---|
| Failure class | 20 | 20/20 = 100% [84%, 100%] | 1.000 [1.000, 1.000] |
| Fooled reason | 6 | 6/6 = 100% | 1.000 [1.000, 1.000] |

Failure class: items either file calls `unclear` are left out (ADR 0003): A 0, B 0.
Fooled reason: scored where both files gave one; only A gave one: 0, only B gave one: 0.

## Failure classes the files disagree on

| A | B | Count |
|---|---|---|
| none | | |
