#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

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

mkdir -p /logs/verifier
if check_test_integrity && pytest . --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_filename_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_ext_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_dirname_variable tests/test_pyqt5ac.py::test_import_module tests/test_pyqt5ac.py::test_without_generation tests/test_pyqt5ac.py::test_ui_generation_when_up_to_date tests/test_pyqt5ac.py::test_resource_generation_when_up_to_date; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
