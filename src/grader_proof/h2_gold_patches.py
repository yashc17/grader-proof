"""Counts the gold patches that H2 would reject, a false negative of the grader (ADR 0009).

Run with `make h2-gold-patches`. Reads the pinned datasets in data/ (`make data-facts` downloads
them) and writes results/h2_gold_patches.json.
"""

import fnmatch
import json
from collections import Counter
from pathlib import PurePosixPath

import polars as pl

from grader_proof.data_facts import DATA_DIR, RESULTS_DIR, SWE_REBENCH_REVISION
from grader_proof.task_builder import (
    CODE_SUFFIXES,
    PROTECTED_CONFIG,
    TEST_DIRS,
    TEST_FILE_PATTERNS,
    Instance,
    parse_file_changes,
    protected_test_files,
)

COLUMNS = ["instance_id", "patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS"]
RULES = ("config_file", "test_file", "existing_file_in_test_dir", "new_code_in_test_dir")


def _in_test_dir(path: str) -> bool:
    return bool(set(PurePosixPath(path).parts[:-1]) & set(TEST_DIRS))


def _is_new_code(path: str) -> bool:
    """Mirrors the new-code pathspecs of `render_integrity_check`."""
    name = PurePosixPath(path).name
    return (
        _in_test_dir(path)
        and name.endswith(CODE_SUFFIXES)
        and not any(fnmatch.fnmatch(name, pattern) for pattern in TEST_FILE_PATTERNS)
        and "__pycache__" not in PurePosixPath(path).parts
    )


def rejecting_rules(instance: Instance) -> set[str]:
    """The H2 rules the gold patch breaks. Empty means H2 accepts it.

    Raises ValueError if a patch cannot be parsed.
    """
    changes = parse_file_changes(instance.patch)
    touched = {path for change in changes for path in change if path is not None}
    existing = {change.old for change in changes if change.old is not None}
    created = {change.new for change in changes if change.new not in (None, change.old)}
    rules = {
        "config_file": any(PurePosixPath(p).name in PROTECTED_CONFIG for p in touched),
        "test_file": bool(touched & set(protected_test_files(instance))),
        "existing_file_in_test_dir": any(_in_test_dir(p) for p in existing),
        "new_code_in_test_dir": any(_is_new_code(p) for p in created),
    }
    return {rule for rule, broken in rules.items() if broken}


def count(rows: pl.DataFrame) -> dict[str, int]:
    counts = Counter(
        {"instances": rows.height, "rejected": 0, "unparseable": 0, **dict.fromkeys(RULES, 0)}
    )
    for row in rows.iter_rows(named=True):
        instance = Instance.model_construct(
            patch=row["patch"],
            test_patch=row["test_patch"],
            fail_to_pass=tuple(row["FAIL_TO_PASS"]),
            pass_to_pass=tuple(row["PASS_TO_PASS"]),
        )
        try:
            rules = rejecting_rules(instance)
        except ValueError:
            counts["unparseable"] += 1
            continue
        counts["rejected"] += bool(rules)
        counts.update(rules)
    return dict(counts)


def main() -> None:
    rows = pl.read_parquet(DATA_DIR / "swe-rebench/*.parquet", columns=COLUMNS)
    with_trajectories = (
        pl.scan_parquet(DATA_DIR / "trajectories/trajectories.parquet")
        .select("instance_id")
        .unique()
        .collect()
    )
    result = {
        "swe_rebench_revision": SWE_REBENCH_REVISION,
        "all_instances": count(rows),
        "instances_with_trajectories": count(rows.join(with_trajectories, on="instance_id")),
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / "h2_gold_patches.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(path.read_text(), end="")


if __name__ == "__main__":
    main()
