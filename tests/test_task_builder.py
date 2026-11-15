import tomllib
from pathlib import Path

import pytest

from grader_proof.held_out import hold_out
from grader_proof.task_builder import (
    CHECK_PROPERTY,
    HELD_OUT_PATCH,
    INTEGRITY,
    PROPERTY_CHECK,
    RESTORE,
    RESTORE_HELD_OUT,
    FileChange,
    Instance,
    parse_file_changes,
    protected_test_files,
    render_dockerfile,
    render_integrity_check,
    render_restore,
    render_restore_held_out,
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
    "install_config": {
        "test_cmd": "pytest --no-header -rA",
        "python": "3.9",
        "install": "pip install -e '.[dev]'",
    },
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
    assert task_dir_name("Org__Repo-12", "h3") == "org__repo-12__h3"
    assert task_dir_name("Org__Repo-12", "h4") == "org__repo-12__h4"


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


def test_dockerfile_installs_the_package_in_the_testbed_env(instance: Instance):
    dockerfile = render_dockerfile(instance)
    install = "source /opt/conda/bin/activate testbed && pip install -e '.[dev]'"
    assert install in dockerfile
    assert dockerfile.index("git apply") < dockerfile.index(install)


def test_dockerfile_without_install_command_has_no_install_step():
    dockerfile = render_dockerfile(
        Instance.from_row({**ROW, "install_config": {"test_cmd": "pytest"}})
    )
    assert "activate testbed" not in dockerfile


def test_dockerfile_strips_future_history_after_applying_the_tests(instance: Instance):
    dockerfile = render_dockerfile(instance)
    assert dockerfile.index("git apply") < dockerfile.index("git gc --prune=now")
    for step in ("git update-ref --no-deref --stdin", "git remote remove", "git reflog expire"):
        assert step in dockerfile


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


H3_PATCH = """\
diff --git a/tests/test_y.py b/tests/test_y.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/tests/test_y.py
@@ -0,0 +1,10 @@
+def test_one():
+    assert True
+
+
+def test_two():
+    assert True
+
+
+def test_old():
+    assert True
"""

H3_ROW = {
    **ROW,
    "test_patch": H3_PATCH,
    "FAIL_TO_PASS": ["tests/test_y.py::test_one", "tests/test_y.py::test_two[a]"],
    "PASS_TO_PASS": ["tests/test_y.py::test_old"],
}


def test_h3_test_sh_restores_held_out_tests_then_runs_every_test():
    script = render_test_sh(Instance.from_row(H3_ROW), "h3")
    assert f"{RESTORE_HELD_OUT}() {{" in script
    assert (
        f"if {RESTORE_HELD_OUT} && pytest --no-header -rA tests/test_y.py::test_one "
        "'tests/test_y.py::test_two[a]' tests/test_y.py::test_old; then"
    ) in script
    assert f"git apply {HELD_OUT_PATCH}" in script


def test_write_task_h3_shows_the_agent_only_the_visible_tests(tmp_path: Path):
    instance = Instance.from_row(H3_ROW)
    split = hold_out(instance.instance_id, instance.test_patch, instance.fail_to_pass)
    task = write_task(instance, tmp_path, "h3")
    assert task == tmp_path / "org__repo-12__h3"
    assert (task / "environment/upstream_tests.patch").read_text() == split.visible_patch
    assert (task / "tests/held_out_tests.patch").read_text() == split.held_out_patch
    assert not (task / "tests/upstream_tests.patch").exists()


def test_write_task_h3_records_the_split_in_the_task_metadata(tmp_path: Path):
    instance = Instance.from_row(H3_ROW)
    split = hold_out(instance.instance_id, instance.test_patch, instance.fail_to_pass)
    config = tomllib.loads((write_task(instance, tmp_path, "h3") / "task.toml").read_text())
    assert config["metadata"] == {
        "visible_fail_to_pass": list(split.visible),
        "held_out_fail_to_pass": list(split.held_out),
    }
    assert len(split.visible) == len(split.held_out) == 1


def test_write_task_h3_refuses_an_instance_with_nothing_to_hold_out(
    instance: Instance, tmp_path: Path
):
    with pytest.raises(ValueError, match="no FAIL_TO_PASS test"):
        write_task(instance, tmp_path, "h3")


def test_other_conditions_have_no_task_metadata(instance: Instance, tmp_path: Path):
    for condition in ("baseline", "h1", "h2"):
        config = tomllib.loads(
            (write_task(instance, tmp_path, condition) / "task.toml").read_text()
        )
        assert "metadata" not in config


def test_all_test_sh_runs_h3_then_h2_then_h1_then_the_tests():
    """H2 compares against the full test patch, so H3 must put the held-out tests back first.
    H1's restore would hide the edits H2 looks for, so H1 runs after H2."""
    instance = Instance.from_row(H3_ROW)
    script = render_test_sh(instance, "all")
    assert (
        f"if {RESTORE_HELD_OUT} && {INTEGRITY} && {RESTORE} && pytest --no-header -rA "
        "tests/test_y.py::test_one 'tests/test_y.py::test_two[a]' tests/test_y.py::test_old; then"
    ) in script
    for check in (
        render_restore_held_out(),
        render_integrity_check(instance),
        render_restore(instance),
    ):
        assert check in script


def test_write_task_all_uses_the_h3_workspace_and_ships_both_patches(tmp_path: Path):
    instance = Instance.from_row(H3_ROW)
    h3 = write_task(instance, tmp_path, "h3")
    everything = write_task(instance, tmp_path, "all")
    assert everything == tmp_path / "org__repo-12__all"
    for name in (
        "instruction.md",
        "task.toml",
        "environment/Dockerfile",
        "environment/upstream_tests.patch",
        "tests/held_out_tests.patch",
        "solution/gold.patch",
    ):
        assert (everything / name).read_text() == (h3 / name).read_text(), name
    assert (everything / "tests/upstream_tests.patch").read_text() == instance.test_patch


def test_write_task_all_refuses_an_instance_h3_refuses(instance: Instance, tmp_path: Path):
    with pytest.raises(ValueError, match="no FAIL_TO_PASS test"):
        write_task(instance, tmp_path, "all")


PROPERTY = "import sys\n\nsys.exit(0)\n"


def write_property(properties_dir: Path, instance_id: str) -> Path:
    properties_dir.mkdir(exist_ok=True)
    path = properties_dir / f"{instance_id}.py"
    path.write_text(PROPERTY)
    return path


def test_h4_test_sh_checks_the_property_then_runs_the_tests(instance: Instance):
    script = render_test_sh(instance, "h4", has_property=True)
    assert f"{CHECK_PROPERTY}() {{" in script
    assert f"python -I {PROPERTY_CHECK}" in script
    assert (
        f"if {CHECK_PROPERTY} && pytest --no-header -rA 'tests/test_x.py::test_new[a b]' "
        "tests/test_x.py::test_old; then"
    ) in script


def test_write_task_h4_ships_the_property_check_to_the_grader(instance: Instance, tmp_path: Path):
    properties = tmp_path / "properties"
    write_property(properties, instance.instance_id)
    baseline = write_task(instance, tmp_path, "baseline", properties_dir=properties)
    h4 = write_task(instance, tmp_path, "h4", properties_dir=properties)
    assert h4 == tmp_path / "org__repo-12__h4"
    assert (h4 / "tests/property_check.py").read_text() == PROPERTY
    assert not (baseline / "tests/property_check.py").exists()
    for name in ("environment/Dockerfile", "environment/upstream_tests.patch", "instruction.md"):
        assert (h4 / name).read_text() == (baseline / name).read_text()


def test_write_task_h4_refuses_an_instance_without_a_property_check(
    instance: Instance, tmp_path: Path
):
    with pytest.raises(ValueError, match="no property check"):
        write_task(instance, tmp_path, "h4", properties_dir=tmp_path / "properties")


def test_all_test_sh_runs_the_property_check_after_h1_where_one_exists():
    script = render_test_sh(Instance.from_row(H3_ROW), "all", has_property=True)
    assert (
        f"if {RESTORE_HELD_OUT} && {INTEGRITY} && {RESTORE} && {CHECK_PROPERTY} && pytest "
    ) in script


def test_write_task_all_adds_h4_only_where_a_property_check_exists(tmp_path: Path):
    instance = Instance.from_row(H3_ROW)
    properties = tmp_path / "properties"
    without = write_task(instance, tmp_path / "without", "all", properties_dir=properties)
    assert CHECK_PROPERTY not in (without / "tests/test.sh").read_text()
    assert not (without / "tests/property_check.py").exists()

    write_property(properties, instance.instance_id)
    with_h4 = write_task(instance, tmp_path / "with", "all", properties_dir=properties)
    assert f"{CHECK_PROPERTY} && pytest" in (with_h4 / "tests/test.sh").read_text()
    assert (with_h4 / "tests/property_check.py").read_text() == PROPERTY
