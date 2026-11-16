# Reproduce check (issue #36, phase 1)

Run on a clean checkout of `origin/main` at 55aa99e, with no `.env` loaded and no Docker. Each target was run, then `git status` was checked. "Match" means the regenerated files are byte-identical to the committed ones.

| Target | Command | Result |
|---|---|---|
| `data-facts` | `make data-facts` (downloads the pinned data, about 2 GB, no key) | Match: `data_facts.json`, `data_facts_by_*.csv` |
| `h2-gold-patches` | `make h2-gold-patches` | Match |
| `held-out-facts` | `make held-out-facts` | Match |
| `history-reads` | `make history-reads` | Match |
| `rules-dev` | `make rules-dev` | Match |
| `judge-dev` | `make judge-dev` with stdin closed, so it could not ask to call the model | Match, every call came from `cache/llm/` |
| `triage-eval` | `make triage-eval`, same way | Match, all calls cached |
| `triage-prevalence` | `make triage-prevalence`, same way | Match, all calls cached |
| `sample` | `make sample` | Keeps the existing `labels/sample.jsonl` |
| `fact-sheets` | `make fact-sheets` | Match |
| `rq1` | `make rq1` | Match |
| `label-agreement` | default run, and the Opus self-agreement run | Match |
| `exploit-review` | `make exploit-review` | Match |
| `redteam-summary` | `make redteam-summary` (reads the committed `results/red_team_runs/`) | Match: `red_team_runs.json`, `red_team.json` |
| `rq3` | `make rq3` (reads the committed replay results, `results/oracle-check` and the verdicts) | Match: `rq3.csv`, `rq3.md` |
| `oracle-check` summary | `uv run python -m grader_proof.oracle_check summarize results/oracle-check` | Match: `oracle_check.csv` (192/192 runs accepted) |
| `figures` | `make figures` | See below |

## Not run

`redteam`, `red-team-trial`, `rq4-runs`, toy tests (Docker and model calls); `oracle-check` and `replay-results` downloads (Actions); `label` (maintainer); `candidates`, `task` (network and Docker Hub); `red-team-pilot` and `replay-export` (need `runs/`, which is not committed). Their committed outputs feed `redteam-summary`, `rq3`, `figures` and `exploit-review`, which match.

## Figures

`main` has no `figures/` folder. The hero figure is in draft PR #77 (branch `m5/35-readme`), which also changes `plotting.py`. With #77's plotting code:

- `figures/hero.png` is byte-identical to the committed file.
- `figures/hero.svg` differed only by trailing spaces, which the `trailing-whitespace` pre-commit hook strips on commit. Fix: `figures/*.svg` is now excluded from that hook in `.pre-commit-config.yaml`. After #77 merges, `make figures` should be run once and the SVG committed, so the committed file equals the fresh output.

## README numbers (PR #77 draft)

Checked against `data_facts.json`, `triage_test.json`, `triage_prevalence.json`, `rq1.csv`, `rq3.csv`, `oracle_check.csv`, `red_team_runs.json` and `labels/exploit_verdicts.jsonl`: all match. The RQ4 rows are pending (#33).

README "Needs" entries that are wrong and should be fixed in #77:

- `redteam-summary` is marked "the laptop's `runs/` folder". It reads the committed `results/red_team_runs/` and needs nothing.
- `rq3` is marked "maintainer (exploit verdicts)". The verdicts are committed, so it needs nothing.
- `exploit-review` is described as summarizing "maintainer" verdicts. They are agent-written (ADR 0016).
