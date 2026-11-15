#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H3: add back the FAIL_TO_PASS tests held out of the agent's workspace.
restore_held_out_tests() {
    git apply --reverse --check /tests/held_out_tests.patch 2>/dev/null ||
        git apply /tests/held_out_tests.patch
}

mkdir -p /logs/verifier
if restore_held_out_tests && pytest . --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_filename_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_ext_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_dirname_variable tests/test_pyqt5ac.py::test_import_module tests/test_pyqt5ac.py::test_without_generation tests/test_pyqt5ac.py::test_ui_generation_when_up_to_date tests/test_pyqt5ac.py::test_resource_generation_when_up_to_date; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
