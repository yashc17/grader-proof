#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

mkdir -p /logs/verifier
if pytest . --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_filename_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_ext_variable tests/test_pyqt5ac.py::test_generation_fails_with_forbidden_dirname_variable tests/test_pyqt5ac.py::test_import_module tests/test_pyqt5ac.py::test_without_generation tests/test_pyqt5ac.py::test_ui_generation_when_up_to_date tests/test_pyqt5ac.py::test_resource_generation_when_up_to_date; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
