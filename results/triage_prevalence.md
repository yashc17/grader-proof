# Failure class prevalence (issue #15)

These are estimates from the triager, not hand labels. The triager makes mistakes, and its
confusion matrix on the 70 test labels (`make triage-eval`, issue #14) belongs next to this
table: a class the triager over-predicts there is over-counted here too.

1000 unresolved trajectories from 880 instances, drawn with seed
15 outside the labeling sample. The rules fired on 149; the judge
(`judge-v2`) classified the rest. Intervals are 95% bootstrap intervals that
resample instances.

| Class | Trajectories | Share | 95% interval |
|---|---|---|---|
| `env_broken` | 6 | 0.6% | 0.1% to 1.2% |
| `task_underspecified` | 161 | 16.1% | 13.8% to 18.5% |
| `upstream_tests_wrong` | 104 | 10.4% | 8.5% to 12.3% |
| `model_failure` | 728 | 72.8% | 69.9% to 75.7% |
| `unclear` | 1 | 0.1% | 0.0% to 0.3% |

Judge outcomes: {'parsed': 850, 'repaired': 0, 'failed': 1}. Judge tokens: 5,651,099 prompt,
255,600 completion, $1.90 at list price.
