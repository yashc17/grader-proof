#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

mkdir -p /logs/verifier
if pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_issue_478.py::TestIssue478::test_async tests/test_issue_478.py::TestIssue478::test_issue; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
