"""Cuts real `git diff` test patches into a visible part and a held-out part (H3).

Each test builds a base commit and an upstream version of the test files, takes the test patch
from `git diff`, and checks the two parts with `git apply`: the visible patch must leave the
held-out functions out of the workspace, and the held-out patch must then give back exactly the
upstream files.
"""

import ast
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from grader_proof.held_out import function_of, hide, hold_out, parse_patch
from grader_proof.task_builder import HELD_OUT_PATCH, RESTORE_HELD_OUT, render_restore_held_out

BASE = {
    "tests/test_mod.py": """\
import pytest


def test_existing():
    assert 1 == 1


def helper():
    return 2


class TestOld:
    def test_a(self):
        x = 1
        y = 2
        assert x + 1 == y

    def test_b(self):
        assert helper() == 2
""",
}

UPSTREAM = {
    "tests/test_mod.py": '''\
import pytest


def test_existing():
    assert 1 + 1 == 2


@pytest.mark.parametrize(
    "value",
    [1, 2],
)
def test_added_top(
    value,
):
    """A docstring
with a line indented less than the body."""
    assert helper() == 2


def helper():
    return 2


class TestOld:
    def test_a(self):
        x = 1
        y = 2
        assert x + 1 == y

    def test_b(self):
        assert helper() == 2

    def test_added_method(self):
        assert helper() == 2
''',
    "tests/test_new.py": """\
from tests.test_mod import helper


def test_one():
    assert helper() == 2


def test_two():
    assert helper() == 2


class TestNew:
    def test_same_name(self):
        assert True

    def test_four(self):
        assert True


class TestOther:
    def test_same_name(self):
        assert True


def test_called():
    assert True


def test_caller():
    test_called()
""",
}

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, env=GIT_ENV, check=True, capture_output=True, text=True
    )
    return result.stdout


def write_files(repo: Path, files: Mapping[str, str]) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository at the base commit."""
    repo = tmp_path / "testbed"
    repo.mkdir()
    git(repo, "init", "-q")
    write_files(repo, BASE)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


@pytest.fixture
def test_patch(repo: Path) -> str:
    write_files(repo, UPSTREAM)
    git(repo, "add", "-A")
    patch = git(repo, "diff", "--cached")
    git(repo, "reset", "-q", "--hard")
    return patch


def apply(repo: Path, patch: str) -> None:
    (repo.parent / "p.patch").write_text(patch)
    git(repo, "apply", str(repo.parent / "p.patch"))


def defined(path: str, text: str) -> set[str]:
    """Test ids of the functions and methods `text` defines, in pytest's `path::Class::f` form."""
    ids: set[str] = set()
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef):
            ids.add(f"{path}::{node.name}")
        if isinstance(node, ast.ClassDef):
            ids |= {
                f"{path}::{node.name}::{f.name}"
                for f in node.body
                if isinstance(f, ast.FunctionDef)
            }
    return ids


def workspace_ids(repo: Path) -> set[str]:
    return set[str]().union(*(defined(p, (repo / p).read_text()) for p in UPSTREAM))


def assert_upstream(repo: Path) -> None:
    for name, text in UPSTREAM.items():
        assert (repo / name).read_text() == text, name


def test_function_of_drops_parameters():
    assert function_of("t.py::T::test_x[a::b-1]") == "t.py::T::test_x"
    assert function_of("t.py::test_x") == "t.py::test_x"


@pytest.mark.parametrize(
    "function",
    [
        "tests/test_mod.py::test_added_top",
        "tests/test_mod.py::TestOld::test_added_method",
        "tests/test_new.py::test_two",
        "tests/test_new.py::TestNew::test_same_name",
    ],
)
def test_hide_leaves_one_function_out_and_gives_it_back(repo: Path, test_patch: str, function: str):
    visible, held_out = hide(test_patch, [function])
    apply(repo, visible)
    upstream_ids = set[str]().union(*(defined(p, text) for p, text in UPSTREAM.items()))
    assert workspace_ids(repo) == upstream_ids - {function}

    apply(repo, held_out)
    assert_upstream(repo)


def test_hide_handles_several_functions_in_one_hunk(repo: Path, test_patch: str):
    functions = ["tests/test_new.py::test_one", "tests/test_new.py::test_two"]
    visible, held_out = hide(test_patch, functions)
    apply(repo, visible)
    assert not workspace_ids(repo) & set(functions)
    apply(repo, held_out)
    assert_upstream(repo)


def test_held_out_patch_applies_after_edits_away_from_the_held_out_tests(
    repo: Path, test_patch: str
):
    visible, held_out = hide(test_patch, ["tests/test_new.py::TestNew::test_four"])
    apply(repo, visible)
    test_new = repo / "tests/test_new.py"
    test_new.write_text(
        test_new.read_text().replace(
            "def test_one():\n    assert helper() == 2", "def test_one():\n    pass"
        )
    )
    apply(repo, held_out)
    assert "tests/test_new.py::TestNew::test_four" in workspace_ids(repo)


@pytest.mark.parametrize(
    ("function", "reason"),
    [
        # The patch edits a function that exists at the base commit.
        ("tests/test_mod.py::test_existing", "added whole"),
        # The patch does not touch the function.
        ("tests/test_mod.py::TestOld::test_a", "added whole"),
        ("tests/test_other.py::test_x", "added whole"),
        ("tests/data.yml::case", "added whole"),
        # Hiding it would leave a call to a name that no longer exists.
        ("tests/test_new.py::test_called", "used elsewhere"),
    ],
)
def test_hide_refuses_functions_it_cannot_hide_cleanly(test_patch: str, function: str, reason: str):
    with pytest.raises(ValueError, match=reason):
        hide(test_patch, [function])


def test_hide_refuses_to_empty_a_class(test_patch: str):
    with pytest.raises(ValueError, match="empty"):
        hide(test_patch, ["tests/test_new.py::TestOther::test_same_name"])


F2P = [
    "tests/test_new.py::test_one",
    "tests/test_new.py::test_two",
    "tests/test_new.py::TestNew::test_four",
    "tests/test_mod.py::test_added_top[1]",
    "tests/test_mod.py::test_added_top[2]",
]


def test_hold_out_holds_out_half_of_the_functions_rounded_down(test_patch: str):
    split = hold_out("org__repo-1", test_patch, F2P)
    held_functions = {function_of(t) for t in split.held_out}
    assert len(held_functions) == 2
    assert sorted(split.visible + split.held_out) == sorted(F2P)


def test_hold_out_keeps_the_cases_of_one_function_together(test_patch: str):
    for instance_id in ("a", "b", "c", "d", "e", "f"):
        split = hold_out(instance_id, test_patch, F2P)
        cases = {"tests/test_mod.py::test_added_top[1]", "tests/test_mod.py::test_added_top[2]"}
        assert cases <= set(split.held_out) or cases <= set(split.visible)


def test_hold_out_is_the_same_on_every_run(test_patch: str):
    assert hold_out("org__repo-1", test_patch, F2P) == hold_out("org__repo-1", test_patch, F2P)


def test_hold_out_skips_functions_it_cannot_hide(test_patch: str):
    f2p = ["tests/test_mod.py::test_existing", "tests/test_new.py::test_two"]
    for instance_id in ("a", "b", "c", "d"):
        split = hold_out(instance_id, test_patch, f2p)
        assert split.held_out == ("tests/test_new.py::test_two",)
        assert split.visible == ("tests/test_mod.py::test_existing",)


def test_hold_out_refuses_when_nothing_can_be_held_out(test_patch: str):
    with pytest.raises(ValueError, match="no FAIL_TO_PASS test"):
        hold_out("a", test_patch, ["tests/test_new.py::test_one"])
    with pytest.raises(ValueError, match="no FAIL_TO_PASS test"):
        hold_out("a", test_patch, ["tests/test_mod.py::test_existing", "tests/test_mod.py::x"])


def restore_held_out(repo: Path, held_out_patch: str) -> int:
    """Runs H3's grading step in `repo` and returns its exit status."""
    patch = repo.parent / "held_out_tests.patch"
    patch.write_text(held_out_patch)
    script = render_restore_held_out().replace(HELD_OUT_PATCH, str(patch))
    run = subprocess.run(["bash", "-c", f"{script}\n{RESTORE_HELD_OUT}\n"], cwd=repo)
    return run.returncode


def test_restore_held_out_adds_the_tests_back_once(repo: Path, test_patch: str):
    visible, held_out = hide(test_patch, ["tests/test_new.py::test_two"])
    apply(repo, visible)
    assert restore_held_out(repo, held_out) == 0
    assert_upstream(repo)
    # The tests are already there when H1's restore step ran first (the All condition).
    assert restore_held_out(repo, held_out) == 0
    assert_upstream(repo)


def test_restore_held_out_fails_if_the_lines_around_the_tests_changed(repo: Path, test_patch: str):
    visible, held_out = hide(test_patch, ["tests/test_new.py::test_two"])
    apply(repo, visible)
    test_new = repo / "tests/test_new.py"
    # The last line of test_one is context for the held-out test_two that follows it.
    test_new.write_text(test_new.read_text().replace("== 2", "== 3", 1))
    assert restore_held_out(repo, held_out) != 0


def round_trip(tmp_path: Path, base: dict[str, str], upstream: dict[str, str], function: str):
    """Hides one function, then checks the workspace before and after the held-out patch.

    The upstream side also creates a file that stays visible, because an empty visible patch is
    refused. Returns the paths the visible patch names.
    """
    upstream = {**upstream, "tests/test_keep.py": "def test_keep():\n    pass\n"}
    repo = tmp_path / "small"
    repo.mkdir()
    git(repo, "init", "-q")
    write_files(repo, base)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base", "--allow-empty")
    write_files(repo, upstream)
    git(repo, "add", "-A")
    # Not git(): text mode would turn "\r\n" into "\n".
    staged = subprocess.run(["git", "diff", "--cached"], cwd=repo, capture_output=True, check=True)
    git(repo, "reset", "-q", "--hard")

    visible, held_out = hide(staged.stdout.decode(), [function])
    apply(repo, visible)
    path, name = function.split("::")
    assert not (repo / path).exists() or f"def {name}(" not in (repo / path).read_text()
    apply(repo, held_out)
    for file, text in upstream.items():
        assert (repo / file).read_bytes() == text.encode(), file
    return [diff.path for diff in parse_patch(visible)]


def test_hide_leaves_out_a_created_file_that_holds_only_held_out_tests(tmp_path: Path):
    upstream = {"tests/test_solo.py": "def test_solo():\n    pass\n"}
    visible = round_trip(tmp_path, {}, upstream, "tests/test_solo.py::test_solo")
    assert visible == ["tests/test_keep.py"]


def test_hide_leaves_out_a_changed_file_whose_only_change_is_held_out(tmp_path: Path):
    base = {"tests/test_a.py": "def test_a():\n    pass\n"}
    upstream = {"tests/test_a.py": "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n"}
    visible = round_trip(tmp_path, base, upstream, "tests/test_a.py::test_b")
    assert visible == ["tests/test_keep.py"]


def test_hide_keeps_carriage_returns(tmp_path: Path):
    upstream = {
        "tests/test_a.py": "def test_a():\r\n    pass\r\n\r\n\r\ndef test_b():\r\n    pass\r\n"
    }
    round_trip(tmp_path, {}, upstream, "tests/test_a.py::test_a")


def test_hide_keeps_a_file_end_without_newline(tmp_path: Path):
    base = {"tests/test_a.py": "def test_a():\n    pass\n\n\nX = 1"}
    upstream = {
        "tests/test_a.py": "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n\n\nX = 1"
    }
    round_trip(tmp_path, base, upstream, "tests/test_a.py::test_b")


def test_hide_refuses_to_leave_the_visible_patch_empty():
    patch = "diff --git a/t.py b/t.py\nnew file mode 100644\n--- /dev/null\n+++ b/t.py\n"
    patch += "@@ -0,0 +1,2 @@\n+def test_a():\n+    pass\n"
    with pytest.raises(ValueError, match="empty"):
        hide(patch, ["t.py::test_a"])
