import tomllib
from pathlib import Path

import pytest

from grader_proof.task_builder import (
    Instance,
    render_dockerfile,
    render_solve_sh,
    render_test_sh,
    task_dir_name,
    write_task,
)

ROW = {
    "instance_id": "Org__Repo-12",
    "base_commit": "abc123",
    "problem_statement": "Something is broken\r\nplease fix\r\n",
    "patch": "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a \n+b",
    "test_patch": "diff --git a/tests/test_x.py b/tests/test_x.py\n",
    "FAIL_TO_PASS": ["tests/test_x.py::test_new[a b]"],
    "PASS_TO_PASS": ["tests/test_x.py::test_old"],
    "install_config": {"test_cmd": "pytest --no-header -rA", "python": "3.9"},
    "docker_image": "swerebench/sweb.eval.x86_64.org_1776_repo-12",
}


@pytest.fixture
def instance() -> Instance:
    return Instance.from_row(ROW)


def test_from_row_maps_dataset_fields(instance: Instance):
    assert instance.instance_id == "Org__Repo-12"
    assert instance.fail_to_pass == ("tests/test_x.py::test_new[a b]",)
    assert instance.pass_to_pass == ("tests/test_x.py::test_old",)
    assert instance.test_cmd == "pytest --no-header -rA"
    assert instance.docker_image == ROW["docker_image"]


def test_from_row_rejects_missing_field():
    row = {k: v for k, v in ROW.items() if k != "patch"}
    with pytest.raises(ValueError, match="patch"):
        Instance.from_row(row)


def test_from_row_rejects_empty_fail_to_pass():
    with pytest.raises(ValueError, match="FAIL_TO_PASS"):
        Instance.from_row({**ROW, "FAIL_TO_PASS": []})


def test_task_dir_name_is_lowercase_and_names_the_condition():
    assert task_dir_name("Org__Repo-12") == "org__repo-12__baseline"


def test_test_sh_runs_every_upstream_test_in_place(instance: Instance):
    script = render_test_sh(instance)
    assert "pytest --no-header -rA 'tests/test_x.py::test_new[a b]' tests/test_x.py::test_old" in (
        script
    )
    assert "git checkout" not in script
    assert "git apply" not in script


def test_test_sh_writes_reward_from_pytest_exit_status(instance: Instance):
    script = render_test_sh(instance)
    assert "/logs/verifier/reward.txt" in script
    assert script.startswith("#!/bin/bash\n")


def test_solve_sh_applies_the_gold_patch_file():
    assert "git apply" in render_solve_sh()
    assert "/solution/gold.patch" in render_solve_sh()


def test_dockerfile_starts_from_image_and_applies_upstream_tests(instance: Instance):
    dockerfile = render_dockerfile(instance)
    assert dockerfile.startswith(f"FROM {instance.docker_image}\n")
    assert "WORKDIR /testbed" in dockerfile
    assert "COPY upstream_tests.patch" in dockerfile
    assert "git apply" in dockerfile


def test_write_task_lays_out_a_harbor_task(instance: Instance, tmp_path: Path):
    task = write_task(instance, tmp_path)
    assert task == tmp_path / "org__repo-12__baseline"
    assert (task / "instruction.md").read_text() == "Something is broken\nplease fix\n"
    assert (task / "solution/gold.patch").read_text() == instance.patch
    assert (task / "environment/upstream_tests.patch").read_text() == instance.test_patch
    assert (task / "tests/test.sh").stat().st_mode & 0o111
    assert (task / "solution/solve.sh").stat().st_mode & 0o111
    config = tomllib.loads((task / "task.toml").read_text())
    assert config["verifier"]["timeout_sec"] > 0


def test_write_task_replaces_an_existing_task(instance: Instance, tmp_path: Path):
    write_task(instance, tmp_path)
    stale = tmp_path / "org__repo-12__baseline" / "stale.txt"
    stale.write_text("old")
    write_task(instance, tmp_path)
    assert not stale.exists()
