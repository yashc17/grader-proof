"""Turns one SWE-rebench instance into a Harbor task under the Baseline condition.

Modeled on Harbor's `swegym` adapter (ADR 0001). Baseline puts the upstream tests in the agent's
workspace and grades in place (ADR 0006), so the Dockerfile applies the test patch at build time
and `test.sh` runs the tests without restoring them.
"""

import argparse
import shlex
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

DATASET_REVISION = "89cdfbab4ab1bd8f5a658bb212d1b63624f4f881"
DATASET_URL = "https://huggingface.co/datasets/nebius/SWE-rebench/resolve/{revision}/data/{file}"
DATASET_FILES = ("test-00000-of-00002.parquet", "test-00001-of-00002.parquet")
CONDITION = "baseline"
AGENT_TIMEOUT_SEC = 1800
VERIFIER_TIMEOUT_SEC = 600


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


def task_dir_name(instance_id: str) -> str:
    """Lowercase, because Docker image names must be."""
    return f"{instance_id.lower()}__{CONDITION}"


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


def render_test_sh(instance: Instance) -> str:
    """Runs every upstream test where the agent left it. pytest exits 0 only if all passed."""
    tests = " ".join(shlex.quote(t) for t in (*instance.fail_to_pass, *instance.pass_to_pass))
    return f"""#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

mkdir -p /logs/verifier
if {instance.test_cmd} {tests}; then
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


def write_task(instance: Instance, tasks_dir: Path) -> Path:
    """Writes the task folder, replacing any earlier version, and returns its path."""
    task = tasks_dir / task_dir_name(instance.instance_id)
    shutil.rmtree(task, ignore_errors=True)
    for sub in ("environment", "tests", "solution"):
        (task / sub).mkdir(parents=True)

    (task / "instruction.md").write_text(render_instruction(instance))
    (task / "task.toml").write_text(render_task_toml())
    (task / "environment/Dockerfile").write_text(render_dockerfile(instance))
    (task / "environment/upstream_tests.patch").write_text(instance.test_patch)
    _write_executable(task / "tests/test.sh", render_test_sh(instance))
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
    parser = argparse.ArgumentParser(description="Write a Baseline Harbor task for one instance.")
    parser.add_argument("instance_id")
    parser.add_argument("--tasks-dir", type=Path, default=Path("tasks"))
    args = parser.parse_args()
    instance = Instance.from_row(fetch_row(args.instance_id))
    print(write_task(instance, args.tasks_dir))


if __name__ == "__main__":
    main()
