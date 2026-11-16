from pathlib import Path

import pytest

from grader_proof.exploit_review import Verdict
from grader_proof.plotting import OraclePoint, RatePoint, hero_series
from grader_proof.rq3 import Attempt, build_rows, write_csv


def attempt(trial: str, condition: str, outcome: str, task: str = "a") -> Attempt:
    return Attempt.model_validate(
        {"task": task, "trial": trial, "condition": condition, "outcome": outcome}
    )


@pytest.fixture
def table(tmp_path: Path) -> Path:
    replay = [
        attempt("x1", "baseline", "accepted"),
        attempt("x2", "baseline", "rejected", task="b"),
        attempt("x1", "h1", "rejected"),
        attempt("x2", "h1", "rejected", task="b"),
        attempt("x1", "h3", "not_applied"),
        attempt("x2", "h3", "not_applied", task="b"),
    ]
    adaptive = [attempt("x1", "baseline", "accepted"), attempt("y1", "all", "rejected")]
    verdicts = [
        Verdict.model_validate(
            {"trial": "x1", "task": "a__baseline", "verdict": "exploit", "category": "edits_tests"}
        )
    ]
    oracle = {("a", "baseline"): (3, 3), ("b", "baseline"): (2, 3), ("a", "all"): (3, 3)}
    path = tmp_path / "rq3.csv"
    write_csv(build_rows(replay, adaptive, verdicts, oracle), path)
    return path


def test_hero_series_reads_rates_for_all_tasks_in_condition_order(table: Path):
    rates, _ = hero_series(table)
    assert [(p.condition, p.measurement) for p in rates] == [
        ("baseline", "replay"),
        ("baseline", "adaptive"),
        ("h1", "replay"),
        ("all", "adaptive"),
    ]


def test_hero_series_keeps_the_interval_and_the_counts(table: Path):
    rates, _ = hero_series(table)
    assert rates[0] == RatePoint(
        condition="baseline",
        measurement="replay",
        rate=0.5,
        low=0.0,
        high=1.0,
        exploits=1,
        graded=2,
    )
    assert rates[3] == RatePoint(
        condition="all", measurement="adaptive", rate=0.0, low=0.0, high=0.0, exploits=0, graded=1
    )


def test_hero_series_leaves_out_conditions_with_nothing_graded(table: Path):
    """Every H3 replay did not apply, so H3 has no rate to plot."""
    rates, _ = hero_series(table)
    assert "h3" not in {p.condition for p in rates}


def test_hero_series_reads_oracle_acceptance_per_condition(table: Path):
    _, oracle = hero_series(table)
    assert oracle == [
        OraclePoint(condition="baseline", accepted=5, runs=6),
        OraclePoint(condition="all", accepted=3, runs=3),
    ]
