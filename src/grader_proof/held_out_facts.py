"""Measures how well H3 holds out tests over every pinned SWE-rebench instance (ADR 0010).

Run with `make held-out-facts`; writes results/held_out_facts.json. The base files are not
available without each instance's image, so each changed file is checked on a stand-in: the base
lines the patch shows, with unique filler lines in the gaps. On it, the visible patch must apply
and leave out every held-out function, and the held-out patch must then give exactly what the
full test patch gives.
"""

import json
import re
import subprocess
import tempfile
from collections import Counter
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import polars as pl

from grader_proof.data_facts import DATA_DIR, RESULTS_DIR
from grader_proof.held_out import CONTEXT, FileDiff, function_of, hold_out, parse_patch


def stand_in_base(diff: FileDiff) -> str:
    """A file the diff applies to: the old-side lines it shows, filler lines elsewhere."""
    lines: list[str] = []
    for hunk in diff.hunks:
        first = hunk.old_start if hunk.old_len else hunk.old_start + 1
        lines += [f"# filler {len(lines) + 1}" for _ in range(first - 1 - len(lines))]
        lines += [line[1:] for line in hunk.lines if line[0] in " -"]
    if diff.hunks and diff.hunks[-1].trailing_context() == CONTEXT:
        lines += [f"# filler {len(lines) + 1}" for _ in range(CONTEXT)]
    no_newline = bool(diff.hunks) and _old_side_ends_without_newline(diff.hunks[-1].lines)
    return "\n".join(lines) + ("" if no_newline or not lines else "\n")


def _old_side_ends_without_newline(lines: tuple[str, ...]) -> bool:
    old_side = [i for i, line in enumerate(lines) if line[0] in " -"]
    last = old_side[-1] if old_side else -1
    return last + 1 < len(lines) and lines[last + 1].startswith("\\")


def _old_path(diff: FileDiff) -> str:
    renamed = [line for line in diff.header if line.startswith("rename from ")]
    assert diff.path is not None
    return renamed[0].removeprefix("rename from ") if renamed else diff.path


def _apply(directory: Path, patch: str) -> bool:
    (directory.parent / "p.patch").write_text(patch)
    command = ["git", "apply", str(directory.parent / "p.patch")]
    return subprocess.run(command, cwd=directory, capture_output=True).returncode == 0


def _defines(text: str, name: str) -> int:
    return len(re.findall(rf"^\s*(?:async\s+)?def\s+{name}\s*\(", text, flags=re.MULTILINE))


def round_trip(test_patch: str, visible_patch: str, held_out_patch: str, held: list[str]) -> str:
    """Checks one instance's patches on stand-ins of the files the held-out patch changes."""
    full = {d.path: d for d in parse_patch(test_patch)}
    visible = {d.path: d for d in parse_patch(visible_patch)}
    for diff in parse_patch(held_out_patch):
        assert diff.path is not None
        names = [f.split("::")[-1] for f in held if f.split("::")[0] == diff.path]
        with tempfile.TemporaryDirectory() as tmp:
            upstream_dir, workspace_dir = Path(tmp, "upstream"), Path(tmp, "workspace")
            original = full[diff.path]
            for directory in (upstream_dir, workspace_dir):
                directory.mkdir()
                if not original.created:
                    target = directory / _old_path(original)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(stand_in_base(original))
            if not _apply(upstream_dir, original.text):
                return "stand_in_failed"
            # A file whose only change is held out is left out of the visible patch.
            if diff.path in visible and not _apply(workspace_dir, visible[diff.path].text):
                return "visible_patch_failed"
            upstream = (upstream_dir / diff.path).read_text()
            in_workspace = workspace_dir / diff.path
            workspace = in_workspace.read_text() if in_workspace.exists() else ""
            if any(_defines(workspace, n) >= _defines(upstream, n) for n in names):
                return "held_out_function_visible"
            if not _apply(workspace_dir, diff.text):
                return "held_out_patch_failed"
            if (workspace_dir / diff.path).read_text() != upstream:
                return "result_differs"
    return "ok"


def measure(row: dict[str, Any]) -> dict[str, Any]:
    functions = {function_of(t) for t in row["FAIL_TO_PASS"]}
    result: dict[str, Any] = {
        "instance_id": row["instance_id"],
        "tests": len(row["FAIL_TO_PASS"]),
        "functions": len(functions),
        "wanted": len(functions) // 2,
        "held": 0,
        "check": None,
    }
    try:
        split = hold_out(row["instance_id"], row["test_patch"], row["FAIL_TO_PASS"])
    except ValueError:
        return result
    held = sorted({function_of(t) for t in split.held_out})
    result["held"] = len(held)
    result["check"] = round_trip(row["test_patch"], split.visible_patch, split.held_out_patch, held)
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    def outcome(r: dict[str, Any]) -> str:
        if r["functions"] == 1:
            return "one_function"
        if r["held"] == r["wanted"]:
            return "full_half_held_out"
        return "part_held_out" if r["held"] else "none_held_out"

    return {
        "instances": len(results),
        "one_fail_to_pass_test": sum(r["tests"] == 1 for r in results),
        "one_fail_to_pass_function": sum(r["functions"] == 1 for r in results),
        "outcomes": dict(Counter(outcome(r) for r in results).most_common()),
        "functions_wanted": sum(r["wanted"] for r in results),
        "functions_held_out": sum(r["held"] for r in results),
        "patch_checks": dict(Counter(r["check"] for r in results if r["check"]).most_common()),
    }


def main() -> None:
    rows = pl.read_parquet(
        DATA_DIR / "swe-rebench/*.parquet",
        columns=["instance_id", "FAIL_TO_PASS", "test_patch", "docker_image"],
    )
    with Pool() as pool:
        results = pool.map(measure, rows.iter_rows(named=True), chunksize=50)
    in_trajectories = set(
        pl.scan_parquet(DATA_DIR / "trajectories/trajectories.parquet")
        .select("instance_id")
        .unique()
        .collect()["instance_id"]
    )
    with_image = set(rows.filter(pl.col("docker_image").is_not_null())["instance_id"])
    facts = {
        "all_instances": summarize(results),
        "trajectory_instances": summarize(
            [r for r in results if r["instance_id"] in in_trajectories]
        ),
        "trajectory_instances_with_image": summarize(
            [r for r in results if r["instance_id"] in in_trajectories & with_image]
        ),
        "failed_checks": sorted(
            f"{r['instance_id']}: {r['check']}" for r in results if r["check"] not in (None, "ok")
        ),
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / "held_out_facts.json"
    out.write_text(json.dumps(facts, indent=2) + "\n")
    print(json.dumps({k: v for k, v in facts.items() if k != "failed_checks"}, indent=2))
    print(f"{len(facts['failed_checks'])} failed checks; wrote {out}")


if __name__ == "__main__":
    main()
