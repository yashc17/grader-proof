#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H3: add back the FAIL_TO_PASS tests held out of the agent's workspace.
restore_held_out_tests() {
    git apply --reverse --check /tests/held_out_tests.patch 2>/dev/null ||
        git apply /tests/held_out_tests.patch
}

# H2: fail if any test file or test config differs from the base commit plus the test patch.
check_test_integrity() (
    index_dir=$(mktemp -d) &&
        export GIT_INDEX_FILE=$index_dir/index GIT_NO_REPLACE_OBJECTS=1 &&
        git read-tree b2d777ac3e04b7457ad967ace9232a6a3a892e9b &&
        git apply --cached /tests/upstream_tests.patch &&
        git diff --quiet --no-ext-diff -- ':(literal).github/workflows/test_on_push.yml' ':(literal)tests/test_pyqt5ac.py' ':(glob)**/conftest.py' ':(glob)**/pytest.ini' ':(glob)**/.pytest.ini' ':(glob)**/pytest.toml' ':(glob)**/.pytest.toml' ':(glob)**/setup.cfg' ':(glob)**/tox.ini' ':(glob)**/pyproject.toml' ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py' ':(glob)**/test/**' ':(glob)**/tests/**' &&
        test -z "$(git ls-files --others -- ':(literal).github/workflows/test_on_push.yml' ':(literal)tests/test_pyqt5ac.py' ':(glob)**/conftest.py' ':(glob)**/pytest.ini' ':(glob)**/.pytest.ini' ':(glob)**/pytest.toml' ':(glob)**/.pytest.toml' ':(glob)**/setup.cfg' ':(glob)**/tox.ini' ':(glob)**/pyproject.toml' ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py')" &&
        test -z "$(git ls-files --others -- ':(glob)**/test/**/*.py' ':(glob)**/test/**/*.pyc' ':(glob)**/test/**/*.so' ':(glob)**/tests/**/*.py' ':(glob)**/tests/**/*.pyc' ':(glob)**/tests/**/*.so' ':(exclude,glob)**/test_*.py' ':(exclude,glob)**/*_test.py' ':(exclude,glob)**/__pycache__/**')"
)

# H1: rewrite every file the upstream test patch touches to its upstream version.
restore_upstream_tests() {
    rm -rf -- .github/workflows/test_on_push.yml tests/test_pyqt5ac.py &&
        git --literal-pathspecs checkout -q b2d777ac3e04b7457ad967ace9232a6a3a892e9b -- .github/workflows/test_on_push.yml tests/test_pyqt5ac.py &&
        git apply /tests/upstream_tests.patch
}

mkdir -p /logs/verifier
if restore_held_out_tests && check_test_integrity && restore_upstream_tests && pytest . --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_filename_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_ext_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_dirname_variable tests/test_pyqt5ac.py::test_import_module tests/test_pyqt5ac.py::test_without_generation tests/test_pyqt5ac.py::test_ui_generation_when_up_to_date tests/test_pyqt5ac.py::test_resource_generation_when_up_to_date; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
