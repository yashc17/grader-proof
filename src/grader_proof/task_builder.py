"""Turns one SWE-rebench instance into a Harbor task under one condition.

Modeled on Harbor's `swegym` adapter (ADR 0001). Every condition puts the upstream tests in the
agent's workspace (ADR 0006), so the Dockerfile applies the test patch at build time. Conditions
differ in what `test.sh` does before it runs the tests:

- baseline: nothing; it runs the tests where the agent left them.
- h1: rewrites every file the test patch touches to its upstream version first (ADR 0008).
"""

import argparse
import re
import shlex
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal, NamedTuple, Self, get_args

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

DATASET_REVISION = "89cdfbab4ab1bd8f5a658bb212d1b63624f4f881"
DATASET_URL = "https://huggingface.co/datasets/nebius/SWE-rebench/resolve/{revision}/data/{file}"
DATASET_FILES = ("test-00000-of-00002.parquet", "test-00001-of-00002.parquet")
Condition = Literal["baseline", "h1"]
CONDITIONS: tuple[Condition, ...] = get_args(Condition)
AGENT_TIMEOUT_SEC = 1800
VERIFIER_TIMEOUT_SEC = 600

# Harbor copies the task's `tests/` folder to `/tests` only after the agent finishes.
GRADING_PATCH = "/tests/upstream_tests.patch"
RESTORE = "restore_upstream_tests"


class Instance(BaseModel):
    """The fields of a SWE-rebench row that a task needs."""

    model_config = ConfigDict(frozen=True)

    instance_id: str
    base_commit: str
    problem_statement: str
    patch: str
    test_patch: str
    fail_to_pass: tuple[str, ...] = Field(alias="FAIL_TO_PASS", min_length=1)
    pass_to_pass: tuple[str, ...] = Field(alias="PASS_TO_PASS")
    test_cmd: str
    docker_image: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Self:
        """Raises ValueError, naming the field, if the row lacks one or holds a bad value."""
        install_config: Mapping[str, Any] = row.get("install_config") or {}
        return cls.model_validate({**row, "test_cmd": install_config.get("test_cmd")})


class FileChange(NamedTuple):
    """One file in a git patch. `old` is None if the patch creates it, `new` if it deletes it."""

    old: str | None
    new: str | None


def parse_file_changes(patch: str) -> list[FileChange]:
    """Reads each file's path before and after a `git diff` patch.

    Raises ValueError for paths git quotes (unusual characters) and for copies, which H1 cannot
    restore without also resetting the copy's source.
    """
    changes: list[FileChange] = []
    for section in re.split(r"^diff --git ", patch, flags=re.MULTILINE)[1:]:
        header, *lines = section.splitlines()
        if header.startswith('"'):
            raise ValueError(f"test patch has a quoted path: {header}")
        if _field(lines, "copy from ") is not None:
            raise ValueError(f"test patch copies a file: {header}")
        old = _field(lines, "rename from ") or _header_path(header)
        new = _field(lines, "rename to ") or _header_path(header)
        if old is None or new is None:
            raise ValueError(f"cannot read the paths of: diff --git {header}")
        if _field(lines, "new file mode ") is not None:
            old = None
        if _field(lines, "deleted file mode ") is not None:
            new = None
        changes.append(FileChange(old, new))
    if not changes:
        raise ValueError("test patch names no file")
    return changes


def _field(lines: list[str], prefix: str) -> str | None:
    """The rest of the first line that starts with `prefix`, or None.

    Diff content lines start with `+`, `-`, a space or `@`, so only git's header lines can match.
    """
    return next((line.removeprefix(prefix) for line in lines if line.startswith(prefix)), None)


def _header_path(header: str) -> str | None:
    """`a/P b/P` gives P, even if P holds spaces. Renames name two paths and give None."""
    path = header[2 : 2 + (len(header) - len("a/ b/")) // 2]
    return path if header == f"a/{path} b/{path}" else None


def task_dir_name(instance_id: str, condition: Condition) -> str:
    """Lowercase, because Docker image names must be."""
    return f"{instance_id.lower()}__{condition}"


def render_instruction(instance: Instance) -> str:
    return instance.problem_statement.replace("\r\n", "\n").strip() + "\n"


def render_task_toml() -> str:
    return f"""[agent]
timeout_sec = {AGENT_TIMEOUT_SEC}

[verifier]
timeout_sec = {VERIFIER_TIMEOUT_SEC}

[environment]
build_timeout_sec = 1800
cpus = 1
memory_mb = 4096
storage_mb = 10240
"""


def render_dockerfile(instance: Instance) -> str:
    return f"""FROM {instance.docker_image}

WORKDIR /testbed

COPY upstream_tests.patch /tmp/upstream_tests.patch
RUN git apply /tmp/upstream_tests.patch && rm /tmp/upstream_tests.patch
"""


def _quote_all(words: Iterable[str]) -> str:
    return " ".join(shlex.quote(w) for w in words)


def render_restore(instance: Instance) -> str:
    """H1: a bash function that rewrites every file the test patch touches to its upstream version.

    It deletes each touched path, checks out the ones that exist at the base commit, and applies
    the test patch again. The base commit, not HEAD, so that commits the agent made do not count.
    """
    changes = parse_file_changes(instance.test_patch)
    touched = sorted({path for change in changes for path in change if path is not None})
    at_base = sorted({change.old for change in changes if change.old is not None})
    steps = [f"rm -rf -- {_quote_all(touched)}"]
    # Without paths, `git checkout <commit> --` would move HEAD instead.
    if at_base:
        commit = shlex.quote(instance.base_commit)
        steps.append(f"git --literal-pathspecs checkout -q {commit} -- {_quote_all(at_base)}")
    steps.append(f"git apply {GRADING_PATCH}")
    body = " &&\n        ".join(steps)
    return f"""
# H1: rewrite every file the upstream test patch touches to its upstream version.
{RESTORE}() {{
    {body}
}}
"""


def render_test_sh(instance: Instance, condition: Condition = "baseline") -> str:
    """Runs every upstream test after the condition's checks. Reward 1 only if all succeed.

    pytest exits 0 only if every listed test was collected and passed.
    """
    checks = {RESTORE: render_restore(instance)} if condition == "h1" else {}
    tests = " ".join(shlex.quote(t) for t in (*instance.fail_to_pass, *instance.pass_to_pass))
    run = " && ".join([*checks, f"{instance.test_cmd} {tests}"])
    return f"""#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed
{"".join(checks.values())}
mkdir -p /logs/verifier
if {run}; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
"""


def render_solve_sh() -> str:
    return """#!/bin/bash
set -euo pipefail

cd /testbed
git apply /solution/gold.patch
"""


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


def write_task(instance: Instance, tasks_dir: Path, condition: Condition = "baseline") -> Path:
    """Writes the task folder, replacing any earlier version, and returns its path."""
    task = tasks_dir / task_dir_name(instance.instance_id, condition)
    shutil.rmtree(task, ignore_errors=True)
    for sub in ("environment", "tests", "solution"):
        (task / sub).mkdir(parents=True)

    (task / "instruction.md").write_text(render_instruction(instance))
    (task / "task.toml").write_text(render_task_toml())
    (task / "environment/Dockerfile").write_text(render_dockerfile(instance))
    (task / "environment/upstream_tests.patch").write_text(instance.test_patch)
    _write_executable(task / "tests/test.sh", render_test_sh(instance, condition))
    if condition == "h1":
        (task / "tests/upstream_tests.patch").write_text(instance.test_patch)
    _write_executable(task / "solution/solve.sh", render_solve_sh())
    (task / "solution/gold.patch").write_text(instance.patch)
    return task


def fetch_row(instance_id: str) -> dict[str, Any]:
    """Reads one row from the pinned SWE-rebench parquet files, without a full download."""
    for file in DATASET_FILES:
        url = DATASET_URL.format(revision=DATASET_REVISION, file=file)
        lazy = pl.scan_parquet(url)
        rows = lazy.filter(instance_id=instance_id).collect()  # pyright: ignore[reportUnknownMemberType]
        if rows.height:
            return rows.row(0, named=True)
    raise KeyError(f"instance {instance_id} is not in SWE-rebench at revision {DATASET_REVISION}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a Harbor task for one instance.")
    parser.add_argument("instance_id")
    parser.add_argument("--condition", choices=CONDITIONS, default="baseline")
    parser.add_argument("--tasks-dir", type=Path, default=Path("tasks"))
    args = parser.parse_args()
    instance = Instance.from_row(fetch_row(args.instance_id))
    print(write_task(instance, args.tasks_dir, args.condition))


if __name__ == "__main__":
    main()
