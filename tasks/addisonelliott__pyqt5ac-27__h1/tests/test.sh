#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H1: rewrite every file the upstream test patch touches to its upstream version.
restore_upstream_tests() {
    rm -rf -- .github/workflows/test_on_push.yml tests/test_pyqt5ac.py &&
        git --literal-pathspecs checkout -q b2d777ac3e04b7457ad967ace9232a6a3a892e9b -- .github/workflows/test_on_push.yml tests/test_pyqt5ac.py &&
        git apply /tests/upstream_tests.patch
}

mkdir -p /logs/verifier
if restore_upstream_tests && pytest . --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_filename_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_ext_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_dirname_variable tests/test_pyqt5ac.py::test_import_module tests/test_pyqt5ac.py::test_without_generation tests/test_pyqt5ac.py::test_ui_generation_when_up_to_date tests/test_pyqt5ac.py::test_resource_generation_when_up_to_date; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
