import polars as pl
import pytest

from grader_proof.data_facts import (
    exit_category,
    self_check_rates,
    self_check_table,
    summarize_by,
)


def make_rows(rows: list[tuple[str, str, str, int, float | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "instance_id": pl.String,
            "repo": pl.String,
            "exit_status": pl.String,
            "resolved": pl.Int64,
            "pred_passes_gen_tests": pl.Float64,
        },
        orient="row",
    )


ROWS = [
    ("a-1", "a/a", "submit", 0, 1.0),
    ("a-1", "a/a", "submit", 0, 1.0),
    ("a-1", "a/a", "submit", 1, 1.0),
    ("a-2", "a/a", "submit", 0, 0.0),
    ("b-1", "b/b", "AgentStuckInLoopError: x", 1, 0.0),
    ("b-1", "b/b", "submit", 0, None),
    ("b-1", "b/b", "submit", 1, None),
]


def test_self_check_table_counts_only_trajectories_with_a_self_check():
    assert self_check_table(make_rows(ROWS)) == {
        "unresolved_passes": 2,
        "unresolved_fails": 1,
        "resolved_passes": 1,
        "resolved_fails": 1,
    }


def test_self_check_rates():
    rates = self_check_rates(self_check_table(make_rows(ROWS)))
    assert rates["pass_rate_unresolved"] == pytest.approx(2 / 3)
    assert rates["pass_rate_resolved"] == pytest.approx(1 / 2)
    assert rates["unresolved_given_pass"] == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("submit", "submit"),
        ("RuntimeError: Agent reached maximum iteration in headless mode.", "turn_limit"),
        ("AgentStuckInLoopError: Agent got stuck in a loop", "stuck_in_loop"),
        ("Timeout: litellm.Timeout: APITimeoutError", "infrastructure_error"),
        ("unknown", "infrastructure_error"),
    ],
)
def test_exit_category(status: str, expected: str):
    assert exit_category(status) == expected


def test_summarize_by_repo():
    out = summarize_by(make_rows(ROWS), "repo").sort("repo")
    a, b = out.to_dicts()
    assert a["repo"] == "a/a"
    assert (a["trajectories"], a["instances"], a["resolved"]) == (4, 2, 1)
    assert a["with_self_check"] == 4
    assert a["pass_rate_unresolved"] == pytest.approx(2 / 3)
    assert (b["trajectories"], b["with_self_check"]) == (3, 1)
    assert b["pass_rate_unresolved"] is None
