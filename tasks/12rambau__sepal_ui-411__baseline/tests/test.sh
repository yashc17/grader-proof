#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

mkdir -p /logs/verifier
if pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_DatePicker.py::TestDatePicker::test_disable tests/test_DatePicker.py::TestDatePicker::test_init tests/test_DatePicker.py::TestDatePicker::test_bind; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
