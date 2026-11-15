"""RQ3 (M3): exploit rates per condition, each technique's effect against Baseline, exploit
categories and oracle acceptance, in one table: a row per condition for all tasks, then the same
rows for each task.

An attempt is one red-team patch graded under one condition, either in the adaptive run (the
agent attacked that condition) or in the replay (a saved Baseline patch regraded). An attempt is
an exploit when the grader accepted it and the maintainer's verdict says exploit (ADR 0006).

A replayed patch that did not apply, and an adaptive trial that got no reward, have no grading
outcome. They are counted as ungraded and left out of rates and effects (design.md, M3).

A technique's effect is the replayed Baseline exploit rate minus its own, on the patches graded
under both, so the attacks are the same and only the grader differs. The Baseline reference is
the replay, not the adaptive run: a replayed patch carries only the repository, so an adaptive
exploit that also changed the environment would otherwise count as stopped by every technique.

Intervals are 95% percentile bootstraps that resample whole tasks (design.md, section 5).
"""

import argparse
import csv
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from grader_proof.exploit_review import VERDICTS_PATH, Verdict, read_verdicts
from grader_proof.oracle_check import TaskResult, split_task_name
from grader_proof.replay import RESULTS, Outcome
from grader_proof.stats import bootstrap_ci
from grader_proof.task_builder import CONDITIONS

SEED = 32
GRADED: tuple[Outcome, ...] = ("accepted", "rejected")


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Attempt(Frozen):
    task: str
    trial: str
    condition: str
    outcome: Outcome


class Estimate(Frozen):
    """A proportion or difference over `n` items, with its interval when one was computed."""

    n: int
    value: float | None = None
    low: float | None = None
    high: float | None = None


class Row(Frozen):
    scope: str
    condition: str
    adaptive_attempts: int
    adaptive_ungraded: int
    adaptive_exploits: int
    adaptive_rate: Estimate | None
    replay_attempts: int
    replay_ungraded: int
    replay_exploits: int
    replay_rate: Estimate
    effect: Estimate | None
    replay_categories: dict[str, int]
    adaptive_categories: dict[str, int]
    oracle_accepted: int
    oracle_runs: int
    # Baseline rows only: patches whose replayed grade differs from their adaptive reward.
    baseline_disagreements: int | None


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _estimate(values: Sequence[float], tasks: Sequence[str], interval: bool) -> Estimate:
    if not values:
        return Estimate(n=0)
    if not interval:
        return Estimate(n=len(values), value=_mean(values))
    low, high = bootstrap_ci(values, _mean, seed=SEED, clusters=tasks)
    return Estimate(n=len(values), value=_mean(values), low=low, high=high)


def _is_exploit(attempt: Attempt, exploits: set[str]) -> bool:
    return attempt.outcome == "accepted" and attempt.trial in exploits


def exploit_rate(attempts: Sequence[Attempt], exploits: set[str], interval: bool) -> Estimate:
    """Exploits over graded attempts. `exploits` holds the trials judged to be exploits."""
    graded = [a for a in attempts if a.outcome in GRADED]
    values = [float(_is_exploit(a, exploits)) for a in graded]
    return _estimate(values, [a.task for a in graded], interval)


def effect(
    baseline: Sequence[Attempt],
    technique: Sequence[Attempt],
    exploits: set[str],
    interval: bool,
) -> Estimate:
    """Baseline's exploit rate minus the technique's, on the patches graded under both."""
    before = {a.trial: a for a in baseline if a.outcome in GRADED}
    pairs = [(before[a.trial], a) for a in technique if a.outcome in GRADED and a.trial in before]
    values = [float(_is_exploit(b, exploits)) - float(_is_exploit(t, exploits)) for b, t in pairs]
    return _estimate(values, [t.task for _, t in pairs], interval)


def baseline_disagreements(
    replay: Iterable[Attempt], adaptive: Iterable[Attempt]
) -> list[tuple[Attempt, Attempt]]:
    """Adaptive Baseline trials whose replay under Baseline was graded differently, as
    (adaptive, replay) pairs. A flakiness check: both grade the same patch with the same grader,
    so they differ only if the grader is flaky or the agent changed something outside the
    repository. Adaptive trials without a reward have nothing to compare."""
    replayed = {a.trial: a for a in replay if a.condition == "baseline"}
    return [
        (a, replayed[a.trial])
        for a in adaptive
        if a.condition == "baseline"
        and a.outcome in GRADED
        and a.trial in replayed
        and replayed[a.trial].outcome != a.outcome
    ]


def missing_verdicts(attempts: Iterable[Attempt], verdicts: Iterable[Verdict]) -> list[str]:
    """Accepted trials that have no verdict yet."""
    judged = {v.trial for v in verdicts}
    return sorted({a.trial for a in attempts if a.outcome == "accepted"} - judged)


def read_adaptive(path: Path) -> list[Attempt]:
    """Reads the trials of a `red_team summarize` file. `task` names the task folder, condition
    included; `task_path` may point to a copy of it, so it is not read."""
    attempts: list[Attempt] = []
    for trial in json.loads(path.read_text())["trials"]:
        task, condition = split_task_name(trial["task"])
        reward = trial["reward"]
        outcome: Outcome = (
            "no_reward" if reward is None else "accepted" if reward == 1 else "rejected"
        )
        attempts.append(
            Attempt(task=task, trial=trial["trial"], condition=condition, outcome=outcome)
        )
    return attempts


def read_replay(results_dir: Path) -> list[Attempt]:
    """Reads every replay result file under `results_dir`."""
    return [
        Attempt(task=r.task, trial=r.trial, condition=r.condition, outcome=r.outcome)
        for path in sorted(results_dir.rglob("*.json"))
        for r in RESULTS.validate_json(path.read_text())
    ]


def read_oracle(results_dir: Path) -> dict[tuple[str, str], tuple[int, int]]:
    """Accepted oracle runs and all oracle runs, by task and condition."""
    results = [TaskResult.model_validate_json(p.read_text()) for p in results_dir.rglob("*.json")]
    return {(r.task, r.condition): (r.accepted, len(r.runs)) for r in results}


def _categories(attempts: Iterable[Attempt], verdicts: Mapping[str, Verdict]) -> dict[str, int]:
    counts = Counter(
        verdicts[a.trial].category
        for a in attempts
        if a.outcome == "accepted" and verdicts[a.trial].verdict == "exploit"
    )
    return {str(category): n for category, n in sorted(counts.items())}


def _row(
    scope: str,
    condition: str,
    replay: Sequence[Attempt],
    adaptive: Sequence[Attempt],
    verdicts: Mapping[str, Verdict],
    oracle: Sequence[tuple[int, int]],
) -> Row:
    exploits = {trial for trial, v in verdicts.items() if v.verdict == "exploit"}
    interval = scope == "all"
    replayed = [a for a in replay if a.condition == condition]
    attacked = [a for a in adaptive if a.condition == condition]
    replay_baseline = [a for a in replay if a.condition == "baseline"]
    return Row(
        scope=scope,
        condition=condition,
        adaptive_attempts=len(attacked),
        adaptive_ungraded=sum(a.outcome not in GRADED for a in attacked),
        adaptive_exploits=sum(_is_exploit(a, exploits) for a in attacked),
        adaptive_rate=exploit_rate(attacked, exploits, interval) if attacked else None,
        replay_attempts=len(replayed),
        replay_ungraded=sum(a.outcome not in GRADED for a in replayed),
        replay_exploits=sum(_is_exploit(a, exploits) for a in replayed),
        replay_rate=exploit_rate(replayed, exploits, interval),
        effect=None
        if condition == "baseline"
        else effect(replay_baseline, replayed, exploits, interval),
        replay_categories=_categories(replayed, verdicts),
        adaptive_categories=_categories(attacked, verdicts),
        oracle_accepted=sum(accepted for accepted, _ in oracle),
        oracle_runs=sum(runs for _, runs in oracle),
        baseline_disagreements=len(baseline_disagreements(replayed, attacked))
        if condition == "baseline"
        else None,
    )


def build_rows(
    replay: Sequence[Attempt],
    adaptive: Sequence[Attempt],
    verdicts: Sequence[Verdict],
    oracle: Mapping[tuple[str, str], tuple[int, int]],
) -> list[Row]:
    """One row per condition for all tasks, then one per task and condition, in `CONDITIONS`
    order. A condition gets a row where it has replay, adaptive or oracle results.

    Every accepted attempt must have a verdict (see `missing_verdicts`).
    """
    by_trial = {v.trial: v for v in verdicts}
    tasks = sorted({a.task for a in (*replay, *adaptive)} | {task for task, _ in oracle})
    rows: list[Row] = []
    for scope in ("all", *tasks):
        scoped_replay = [a for a in replay if scope in ("all", a.task)]
        scoped_adaptive = [a for a in adaptive if scope in ("all", a.task)]
        scoped_oracle = {key: n for key, n in oracle.items() if scope in ("all", key[0])}
        present = {a.condition for a in (*scoped_replay, *scoped_adaptive)}
        present |= {condition for _, condition in scoped_oracle}
        for condition in (c for c in CONDITIONS if c in present):
            oracle_counts = [v for (_, c), v in scoped_oracle.items() if c == condition]
            rows.append(
                _row(scope, condition, scoped_replay, scoped_adaptive, by_trial, oracle_counts)
            )
    return rows


def _number(value: float | None) -> str:
    return "" if value is None else f"{value:.4g}"


def _estimate_cells(estimate: Estimate | None) -> list[str]:
    if estimate is None:
        return ["", "", ""]
    return [_number(estimate.value), _number(estimate.low), _number(estimate.high)]


def _counts(categories: Mapping[str, int]) -> str:
    return " ".join(f"{name}={n}" for name, n in categories.items())


CSV_HEADER = [
    "scope",
    "condition",
    "adaptive_attempts",
    "adaptive_ungraded",
    "adaptive_exploits",
    "adaptive_rate",
    "adaptive_rate_low",
    "adaptive_rate_high",
    "replay_attempts",
    "replay_ungraded",
    "replay_exploits",
    "replay_rate",
    "replay_rate_low",
    "replay_rate_high",
    "effect",
    "effect_low",
    "effect_high",
    "replay_categories",
    "adaptive_categories",
    "oracle_accepted",
    "oracle_runs",
    "baseline_disagreements",
]


def write_csv(rows: Sequence[Row], path: Path) -> None:
    with path.open("w", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        for r in rows:
            writer.writerow(
                [
                    r.scope,
                    r.condition,
                    r.adaptive_attempts,
                    r.adaptive_ungraded,
                    r.adaptive_exploits,
                    *_estimate_cells(r.adaptive_rate),
                    r.replay_attempts,
                    r.replay_ungraded,
                    r.replay_exploits,
                    *_estimate_cells(r.replay_rate),
                    *_estimate_cells(r.effect),
                    _counts(r.replay_categories),
                    _counts(r.adaptive_categories),
                    r.oracle_accepted,
                    r.oracle_runs,
                    "" if r.baseline_disagreements is None else r.baseline_disagreements,
                ]
            )


def _percent(value: float) -> str:
    return f"{value:.0%}"


def _rate_cell(exploits: int, estimate: Estimate | None) -> str:
    if estimate is None:
        return ""
    if estimate.value is None:
        return "none graded"
    cell = f"{exploits}/{estimate.n} = {_percent(estimate.value)}"
    if estimate.low is not None and estimate.high is not None:
        cell += f" [{_percent(estimate.low)}, {_percent(estimate.high)}]"
    return cell


def _effect_cell(estimate: Estimate | None) -> str:
    if estimate is None:
        return ""
    if estimate.value is None:
        return "none graded"

    def points(value: float) -> str:
        return f"{value * 100:+.0f} pp"

    cell = f"{points(estimate.value)} (n={estimate.n})"
    if estimate.low is not None and estimate.high is not None:
        cell += f" [{points(estimate.low)}, {points(estimate.high)}]"
    return cell


LEGEND = """
- Rates are exploits over graded attempts. Ungraded: the replayed patch did not apply, or the
  adaptive trial got no reward. Exploit means accepted and judged an exploit by the maintainer.
- Effect: replayed Baseline exploit rate minus the condition's, on the patches graded under both,
  in percentage points. Positive means the technique stopped exploits.
- Brackets: 95% percentile bootstrap resampling tasks, 10,000 resamples, fixed seed. Only the
  rows for all tasks have them.
- Replay is not a fair test of H3, or of the H3 part of All: the Baseline red team saw the
  held-out tests (ADR 0010, known gap (a)). The adaptive run against All is.
- Oracle: oracle-check runs that the grader accepted. Any shortfall is a false negative.
- Replay differs: on Baseline rows, the patches whose replayed Baseline grade differs from their
  adaptive reward (listed below). The grader is the same, so a difference means flakiness or an
  agent change outside the repository, which a replayed patch cannot carry.
"""


def render_markdown(rows: Sequence[Row], disagreements: Sequence[tuple[Attempt, Attempt]]) -> str:
    """The table, its legend, and the list of Baseline replays that differ from the adaptive run."""
    header = (
        "| Scope | Condition | Adaptive exploits | Adaptive ungraded | Replay exploits "
        "| Replay ungraded | Effect vs Baseline | Replay categories | Adaptive categories "
        "| Oracle | Replay differs |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = [
        f"| {r.scope} | {r.condition} | {_rate_cell(r.adaptive_exploits, r.adaptive_rate)} "
        f"| {r.adaptive_ungraded if r.adaptive_attempts else ''} "
        f"| {_rate_cell(r.replay_exploits, r.replay_rate)} | {r.replay_ungraded} "
        f"| {_effect_cell(r.effect)} | {_counts(r.replay_categories)} "
        f"| {_counts(r.adaptive_categories)} "
        f"| {f'{r.oracle_accepted}/{r.oracle_runs}' if r.oracle_runs else ''} "
        f"| {'' if r.baseline_disagreements is None else r.baseline_disagreements} |"
        for r in rows
    ]
    listed = "".join(
        f"- {replayed.trial} ({replayed.task}): adaptive {adaptive.outcome}, "
        f"replay {replayed.outcome}\n"
        for adaptive, replayed in disagreements
    )
    check = (
        "\n## Flakiness check\n\nBaseline patches whose replayed Baseline grade differs from "
        f"the adaptive reward: {len(disagreements)}\n\n{listed}"
    )
    title = "# RQ3: exploit rates by condition\n\n"
    return title + header + "\n".join(lines) + "\n" + LEGEND + check


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True, help="replay results folder")
    parser.add_argument("--adaptive", type=Path, help="red_team summarize JSON of the M3 runs")
    parser.add_argument("--verdicts", type=Path, default=VERDICTS_PATH)
    parser.add_argument("--oracle", type=Path, default=Path("results/oracle-check"))
    parser.add_argument("--out", type=Path, default=Path("results/rq3"), help="writes .csv and .md")
    args = parser.parse_args()

    replay = read_replay(args.replay)
    adaptive = read_adaptive(args.adaptive) if args.adaptive else []
    verdicts = read_verdicts(args.verdicts)
    if not replay:
        raise SystemExit(f"no replay results under {args.replay}")
    if rerun := sorted(f"{a.trial} [{a.condition}]" for a in replay if a.outcome == "no_reward"):
        raise SystemExit("replays with no reward, rerun them:\n" + "\n".join(rerun))
    if missing := missing_verdicts([*replay, *adaptive], verdicts):
        raise SystemExit(
            f"accepted trials without a verdict in {args.verdicts}:\n" + "\n".join(missing)
        )

    rows = build_rows(replay, adaptive, verdicts, read_oracle(args.oracle))
    table = render_markdown(rows, baseline_disagreements(replay, adaptive))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_csv(rows, args.out.with_suffix(".csv"))
    args.out.with_suffix(".md").write_text(table)
    print(table)


if __name__ == "__main__":
    main()
