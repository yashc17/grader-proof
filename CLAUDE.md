# grader-proof

Read [CONTEXT.md](CONTEXT.md) for terms and [docs/design.md](docs/design.md) for the plan before working. Decisions are in [docs/adr/](docs/adr/).

## Working rules

- Every change maps to a GitHub issue. Follow [CONTRIBUTING.md](CONTRIBUTING.md) for branches, commits and PRs.
- Ask the maintainer before any push or destructive git operation. The hook in `.claude/hooks/` blocks force-pushes, pushes to `main` and commands that discard work.
- Write tests first for parsing, metrics and grader logic. Skip tests for glue code.
- Never invent results, citations or dataset facts. If something cannot be verified, add it to the open questions in `docs/design.md`.
- Estimate the cost of any batch of model calls before running it. All calls go through the cached client (ADR 0004). Budget: $0 cash, at most $50 of Tinker credit.
- The maintainer's dev labels (`labels/human.jsonl`) and exploit verdicts belong to the maintainer. Never write or edit them. The 70 test labels are written by a Claude Opus 5.5 labeler session (ADR 0015); other sessions never edit them.
- Prose: plain, short sentences, numbers instead of adjectives, glossary terms used exactly. Never use: comprehensive, robust, seamless, leverage, cutting-edge, delve.

## Agent skills

The installed skill names differ from some common ones: `to-spec` writes PRDs, `to-tickets` writes issues, `diagnosing-bugs` diagnoses, and `grill-me` runs `grilling`.

### Issue tracker

Issues and PRDs are GitHub issues in `yashc17/grader-proof`, managed with `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single context: `CONTEXT.md` and `docs/adr/` at the root. See `docs/agents/domain.md`.
