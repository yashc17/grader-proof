import pytest

from grader_proof.h2_gold_patches import rejecting_rules
from grader_proof.task_builder import Instance

TEST_PATCH = """\
diff --git a/tests/test_x.py b/tests/test_x.py
new file mode 100644
"""


def modifies(path: str) -> str:
    return f"diff --git a/{path} b/{path}\nindex 1111111..2222222 100644\n"


def creates(path: str) -> str:
    return f"diff --git a/{path} b/{path}\nnew file mode 100644\n"


def gold(patch: str) -> Instance:
    return Instance.model_construct(
        patch=patch,
        test_patch=TEST_PATCH,
        fail_to_pass=("tests/test_x.py::test_a",),
        pass_to_pass=("pkg/test_y.py::test_b", "pkg/mod.py::pkg.mod.f"),
    )


@pytest.mark.parametrize(
    ("patch", "rules"),
    [
        (modifies("pkg/mod.py"), set()),
        (creates("tests/data.txt"), set()),
        (creates("tests/test_new.py"), set()),
        (creates("tests/__pycache__/mod.cpython-312.pyc"), set()),
        (creates("tests/helpers.py"), {"new_code_in_test_dir"}),
        (creates("pkg/test/fake/mod.so"), {"new_code_in_test_dir"}),
        (modifies("sub/pyproject.toml"), {"config_file"}),
        (creates("pkg/conftest.py"), {"config_file"}),
        (modifies("pkg/test_y.py"), {"test_file"}),
        (modifies("pkg/tests/helpers.py"), {"existing_file_in_test_dir"}),
        (modifies("tests/test_x.py"), {"test_file", "existing_file_in_test_dir"}),
        (
            modifies("setup.cfg") + modifies("test/data.json"),
            {"config_file", "existing_file_in_test_dir"},
        ),
    ],
)
def test_rejecting_rules_names_each_h2_rule_the_gold_patch_breaks(patch: str, rules: set[str]):
    assert rejecting_rules(gold(patch)) == rules
