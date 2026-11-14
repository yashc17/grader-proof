import tomllib
from pathlib import Path

import pytest

from grader_proof.task_builder import (
    INTEGRITY,
    RESTORE,
    FileChange,
    Instance,
    parse_file_changes,
    protected_test_files,
    render_dockerfile,
    render_integrity_check,
    render_restore,
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
    assert task_dir_name("Org__Repo-12", "baseline") == "org__repo-12__baseline"
    assert task_dir_name("Org__Repo-12", "h1") == "org__repo-12__h1"
    assert task_dir_name("Org__Repo-12", "h2") == "org__repo-12__h2"


MODIFIED = """\
diff --git a/tests/test_mod.py b/tests/test_mod.py
index 1111111..2222222 100644
--- a/tests/test_mod.py
+++ b/tests/test_mod.py
@@ -1 +1,2 @@
 def test_a(): pass
+def test_b(): pass
"""

# Git ends `---`/`+++` paths that hold a space with a tab.
CREATED = """\
diff --git a/tests/test new.py b/tests/test new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/tests/test new.py\t
@@ -0,0 +1 @@
+def test_new(): pass
"""

DELETED = """\
diff --git a/tests/test_gone.py b/tests/test_gone.py
deleted file mode 100644
index 4444444..0000000
--- a/tests/test_gone.py
+++ /dev/null
@@ -1 +0,0 @@
-def test_old(): pass
"""

RENAMED = """\
diff --git a/tests/old.py b/tests/new.py
similarity index 100%
rename from tests/old.py
rename to tests/new.py
"""

BINARY = """\
diff --git a/tests/data.bin b/tests/data.bin
new file mode 100644
index 0000000..5555555
Binary files /dev/null and b/tests/data.bin differ
"""

PATCH = MODIFIED + CREATED + DELETED + RENAMED + BINARY


def test_parse_file_changes_names_each_file_before_and_after_the_patch():
    assert parse_file_changes(PATCH) == [
        FileChange(old="tests/test_mod.py", new="tests/test_mod.py"),
        FileChange(old=None, new="tests/test new.py"),
        FileChange(old="tests/test_gone.py", new=None),
        FileChange(old="tests/old.py", new="tests/new.py"),
        FileChange(old=None, new="tests/data.bin"),
    ]


def test_parse_file_changes_rejects_quoted_paths():
    patch = 'diff --git "a/tests/t\\303\\251.py" "b/tests/t\\303\\251.py"\n'
    with pytest.raises(ValueError, match="quoted"):
        parse_file_changes(patch)


def test_parse_file_changes_rejects_text_that_is_not_a_git_patch():
    with pytest.raises(ValueError, match="no file"):
        parse_file_changes("--- a/x.py\n+++ b/x.py\n")


def test_test_sh_runs_every_upstream_test_in_place(instance: Instance):
    script = render_test_sh(instance)
    assert "pytest --no-header -rA 'tests/test_x.py::test_new[a b]' tests/test_x.py::test_old" in (
        script
    )
    assert "git checkout" not in script
    assert "git apply" not in script


def test_baseline_test_sh_does_not_restore(instance: Instance):
    assert RESTORE not in render_test_sh(instance, "baseline")


def test_h1_test_sh_restores_before_running_the_tests(instance: Instance):
    script = render_test_sh(instance, "h1")
    assert render_restore(instance) in script
    assert f"if {RESTORE} && pytest --no-header -rA " in script


def test_restore_resets_files_from_the_base_commit():
    restore = render_restore(Instance.from_row({**ROW, "test_patch": PATCH}))
    assert (
        "rm -rf -- tests/data.bin tests/new.py tests/old.py 'tests/test new.py' "
        "tests/test_gone.py tests/test_mod.py"
    ) in restore
    assert (
        "git --literal-pathspecs checkout -q abc123 -- "
        "tests/old.py tests/test_gone.py tests/test_mod.py"
    ) in restore
    assert "git apply /tests/upstream_tests.patch" in restore


def test_restore_skips_checkout_when_the_patch_only_creates_files():
    """`git checkout <commit> --` with no paths would move HEAD instead of restoring files."""
    restore = render_restore(Instance.from_row({**ROW, "test_patch": CREATED + BINARY}))
    assert "git checkout" not in restore
    assert "git apply /tests/upstream_tests.patch" in restore


def test_baseline_and_h1_test_sh_do_not_check_integrity(instance: Instance):
    assert INTEGRITY not in render_test_sh(instance, "baseline")
    assert INTEGRITY not in render_test_sh(instance, "h1")


def test_h2_test_sh_checks_integrity_before_running_the_tests(instance: Instance):
    script = render_test_sh(instance, "h2")
    assert render_integrity_check(instance) in script
    assert f"if {INTEGRITY} && pytest --no-header -rA " in script
    assert RESTORE not in script


def test_protected_test_files_are_patch_paths_and_test_files_the_grader_runs():
    instance = Instance.from_row(
        {
            **ROW,
            "test_patch": PATCH,
            "FAIL_TO_PASS": ["tests/test_mod.py::test_b", "tests/unit/check_test.py::test_c[x::y]"],
            "PASS_TO_PASS": [
                "tests/test_other.py::Suite::test_d",
                "pkg/doc.py::pkg.doc.g",
                "tests/typing/test_types.yml::case",
                "Test",
            ],
        }
    )
    assert protected_test_files(instance) == [
        "tests/data.bin",
        "tests/new.py",
        "tests/old.py",
        "tests/test new.py",
        "tests/test_gone.py",
        "tests/test_mod.py",
        "tests/test_other.py",
        "tests/unit/check_test.py",
    ]


def test_integrity_check_compares_against_the_base_commit_and_the_test_patch():
    check = render_integrity_check(Instance.from_row({**ROW, "test_patch": CREATED}))
    assert "git read-tree abc123" in check
    assert "git apply --cached /tests/upstream_tests.patch" in check
    assert "':(literal)tests/test new.py'" in check
    assert "':(glob)**/conftest.py'" in check


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


def test_write_task_h1_ships_the_test_patch_to_the_grader(instance: Instance, tmp_path: Path):
    baseline = write_task(instance, tmp_path, "baseline")
    h1 = write_task(instance, tmp_path, "h1")
    assert h1 == tmp_path / "org__repo-12__h1"
    assert (h1 / "tests/upstream_tests.patch").read_text() == instance.test_patch
    assert not (baseline / "tests/upstream_tests.patch").exists()
    for name in ("environment/Dockerfile", "environment/upstream_tests.patch", "instruction.md"):
        assert (h1 / name).read_text() == (baseline / name).read_text()


def test_write_task_h2_ships_the_test_patch_to_the_grader(instance: Instance, tmp_path: Path):
    baseline = write_task(instance, tmp_path, "baseline")
    h2 = write_task(instance, tmp_path, "h2")
    assert h2 == tmp_path / "org__repo-12__h2"
    assert (h2 / "tests/upstream_tests.patch").read_text() == instance.test_patch
    for name in ("environment/Dockerfile", "environment/upstream_tests.patch", "instruction.md"):
        assert (h2 / name).read_text() == (baseline / name).read_text()


def test_write_task_replaces_an_existing_task(instance: Instance, tmp_path: Path):
    write_task(instance, tmp_path)
    stale = tmp_path / "org__repo-12__baseline" / "stale.txt"
    stale.write_text("old")
    write_task(instance, tmp_path)
    assert not stale.exists()
