"""Regenerates the data facts in docs/design.md section 3 from the pinned datasets.

Run with `make data-facts`. The `trajectory` column is never read.
"""

import json
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from grader_proof.stats import bootstrap_ci

TRAJECTORIES_REVISION = "35455389ab51bf5e2306bfd436ef72d0f98bf882"
SWE_REBENCH_REVISION = "89cdfbab4ab1bd8f5a658bb212d1b63624f4f881"

HF = "https://huggingface.co/datasets/nebius"
DOWNLOADS = {
    "trajectories/trajectories.parquet": (
        f"{HF}/SWE-rebench-openhands-trajectories/resolve/{TRAJECTORIES_REVISION}"
        "/trajectories.parquet"
    ),
    "swe-rebench/test-00000-of-00002.parquet": (
        f"{HF}/SWE-rebench/resolve/{SWE_REBENCH_REVISION}/data/test-00000-of-00002.parquet"
    ),
    "swe-rebench/test-00001-of-00002.parquet": (
        f"{HF}/SWE-rebench/resolve/{SWE_REBENCH_REVISION}/data/test-00001-of-00002.parquet"
    ),
}
DATA_DIR = Path("data")
RESULTS_DIR = Path("results")

BOOTSTRAP_SEED = 0

SELF_CHECK_COLUMNS = ["instance_id", "repo", "exit_status", "resolved", "pred_passes_gen_tests"]


def download_missing() -> None:
    """Downloads each pinned file that is not already in data/."""
    for name, url in DOWNLOADS.items():
        path = DATA_DIR / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        print(f"downloading {name}")
        with urllib.request.urlopen(url) as response, partial.open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
        partial.rename(path)


def exit_category(exit_status: str) -> str:
    if exit_status == "submit":
        return "submit"
    if exit_status.startswith("RuntimeError: Agent reached max"):
        return "turn_limit"
    if exit_status.startswith("AgentStuckInLoopError"):
        return "stuck_in_loop"
    return "infrastructure_error"


def self_check_table(df: pl.DataFrame) -> dict[str, int]:
    """Counts trajectories that have a self-check by resolved and self-check result."""
    checked = df.filter(pl.col("pred_passes_gen_tests").is_not_null())
    resolved = pl.col("resolved") == 1
    passes = pl.col("pred_passes_gen_tests") == 1
    counts = checked.select(
        unresolved_passes=(~resolved & passes).sum(),
        unresolved_fails=(~resolved & ~passes).sum(),
        resolved_passes=(resolved & passes).sum(),
        resolved_fails=(resolved & ~passes).sum(),
    )
    return counts.row(0, named=True)


def self_check_rates(table: dict[str, int]) -> dict[str, float]:
    return {
        "pass_rate_unresolved": table["unresolved_passes"]
        / (table["unresolved_passes"] + table["unresolved_fails"]),
        "pass_rate_resolved": table["resolved_passes"]
        / (table["resolved_passes"] + table["resolved_fails"]),
        "unresolved_given_pass": table["unresolved_passes"]
        / (table["unresolved_passes"] + table["resolved_passes"]),
    }


def summarize_by(df: pl.DataFrame, key: str) -> pl.DataFrame:
    """One row per `key` value: counts and the self-check pass rate on unresolved trajectories."""
    unresolved_checked = (pl.col("resolved") == 0) & pl.col("pred_passes_gen_tests").is_not_null()
    return df.group_by(key).agg(
        trajectories=pl.len(),
        instances=pl.col("instance_id").n_unique(),
        resolved=(pl.col("resolved") == 1).sum(),
        with_self_check=pl.col("pred_passes_gen_tests").is_not_null().sum(),
        pass_rate_unresolved=(pl.col("pred_passes_gen_tests").filter(unresolved_checked).mean()),
    )


def self_check_intervals(df: pl.DataFrame) -> dict[str, tuple[float, float]]:
    """95% bootstrap intervals for the self-check rates, resampling whole instances."""
    checked = df.filter(pl.col("pred_passes_gen_tests").is_not_null())
    outcomes = list(
        zip(
            checked["resolved"].to_list(),
            (checked["pred_passes_gen_tests"] == 1).cast(pl.Int64).to_list(),
            strict=True,
        )
    )
    clusters = checked["instance_id"].to_list()

    def rate(want_resolved: int, given_pass: bool = False):
        def statistic(sample: Sequence[tuple[int, int]]) -> float:
            if given_pass:
                passing = [resolved for resolved, passes in sample if passes]
                return passing.count(want_resolved) / len(passing)
            group = [passes for resolved, passes in sample if resolved == want_resolved]
            return sum(group) / len(group)

        return statistic

    statistics = {
        "pass_rate_unresolved": rate(0),
        "pass_rate_resolved": rate(1),
        "unresolved_given_pass": rate(0, given_pass=True),
    }
    return {
        name: bootstrap_ci(
            outcomes,
            statistic,
            seed=BOOTSTRAP_SEED,
            clusters=clusters,
        )
        for name, statistic in statistics.items()
    }


def compute_facts() -> tuple[dict[str, object], pl.DataFrame, pl.DataFrame]:
    trajectories = pl.scan_parquet(DATA_DIR / "trajectories/trajectories.parquet")
    df = trajectories.select(*SELF_CHECK_COLUMNS, "gen_tests_correct").collect()
    df = df.with_columns(
        exit_category=pl.col("exit_status").map_elements(exit_category, return_dtype=pl.String)
    )

    per_instance = df.group_by("instance_id").agg(
        n=pl.len(), n_resolved=(pl.col("resolved") == 1).sum()
    )
    image_names = (
        pl.scan_parquet(DATA_DIR / "swe-rebench/*.parquet")
        .select("instance_id", "image_name")
        .collect()
    )
    with_image = per_instance.join(
        image_names.filter(pl.col("image_name").is_not_null()), on="instance_id"
    )
    table = self_check_table(df)
    unresolved_passing = df.filter(
        (pl.col("resolved") == 0) & (pl.col("pred_passes_gen_tests") == 1)
    )

    facts: dict[str, object] = {
        "revisions": {
            "trajectories": TRAJECTORIES_REVISION,
            "swe_rebench": SWE_REBENCH_REVISION,
        },
        "trajectories": df.height,
        "instances": per_instance.height,
        "repositories": df["repo"].n_unique(),
        "trajectories_per_instance": {
            "mean": per_instance["n"].mean(),
            "min": per_instance["n"].min(),
            "max": per_instance["n"].max(),
        },
        "resolved": int((df["resolved"] == 1).sum()),
        "resolved_rate": df["resolved"].mean(),
        "instances_with_resolved_and_unresolved": int(
            (
                (per_instance["n_resolved"] > 0) & (per_instance["n_resolved"] < per_instance["n"])
            ).sum()
        ),
        "exit_category": dict(df["exit_category"].value_counts().sort("exit_category").iter_rows()),
        "with_self_check": int(df["pred_passes_gen_tests"].is_not_null().sum()),
        "self_check_table": table,
        "self_check_rates": self_check_rates(table),
        "self_check_rate_intervals_95": self_check_intervals(df),
        "unresolved_passing_with_correct_self_check": int(
            (unresolved_passing["gen_tests_correct"] == 1).sum()
        ),
        "instances_in_swe_rebench": int(per_instance.join(image_names, on="instance_id").height),
        "instances_with_image": with_image.height,
        "images_x86_64": int(
            with_image.join(image_names, on="instance_id")["image_name"]
            .str.contains("x86_64")
            .sum()
        ),
    }
    return (
        facts,
        summarize_by(df, "repo").sort("repo"),
        summarize_by(df, "exit_category").sort("exit_category"),
    )


def main() -> None:
    download_missing()
    facts, by_repo, by_exit = compute_facts()
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "data_facts.json").write_text(json.dumps(facts, indent=2) + "\n")
    by_repo.write_csv(RESULTS_DIR / "data_facts_by_repo.csv")
    by_exit.write_csv(RESULTS_DIR / "data_facts_by_exit_status.csv")
    print(json.dumps(facts, indent=2))


if __name__ == "__main__":
    main()
