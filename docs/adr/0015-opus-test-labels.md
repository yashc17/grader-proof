# The 70 test labels are written by Claude Opus 5.5

Decided by the maintainer on 2026-11-15. This replaces the plan in design.md §4 that the maintainer hand-labels the 70 test items.

## Why

The test items need a careful reading of the issue, the upstream tests, the agent's patch and the trajectory. The maintainer found most of them too code-heavy to judge with confidence. A labeler who cannot read the code gives labels that are noisy in ways nobody can measure.

The triager under test is a 9B open model (`Qwen/Qwen3.5-9B-Base`) with rules in front of it. Claude Opus 5.5 is a far stronger model at reading code. Its labels are a stronger reference for this triager than labels from a reader who cannot follow the code, so they serve as ground truth for RQ2.

## How

- One Claude Opus 5.5 session labels each test item from the issue, the gold patch, the upstream test patch, the full trajectory and the label-free fact sheets (issue #9). It writes `labels/opus_test.jsonl` (the `Label` schema in `labeling.py`) and 2–4 sentences of evidence per item in `labels/opus_test_evidence.jsonl`.
- It applies ADR 0003's classes and precedence order, and writes down the decision rules it used in `docs/codebook.md`.
- It labels blind: it never sees the maintainer's labels or any triager output. No triager prediction on a test item exists before the labels are final.
- It also labels the 30 dev items blind, into `labels/opus_dev.jsonl`. Cohen's κ between these and the maintainer's dev labels measures how close the two labelers are.
- Self-agreement (#10) becomes a second, fresh Opus session that re-labels 20 random test items without seeing the first labels.

## Consequences

- RQ2's κ measures agreement between the triager and Opus labels, not human labels. The write-up says so wherever it reports κ.
- The triager was tuned on the maintainer's dev labels and is scored on Opus test labels. The Opus-against-maintainer κ on dev shows how large that shift is, and is reported next to the headline κ.
- An Opus labeler may share blind spots with the LLM judge. The two models differ greatly in size, and the judge's prompt was frozen before any Opus label existed, which limits this. The risk is stated as a limitation.
- Exploit verdicts (#31) stay with the maintainer.
