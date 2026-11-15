#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H1: rewrite every file the upstream test patch touches to its upstream version.
restore_upstream_tests() {
    rm -rf -- tests/test_issue_478.py &&
        git apply /tests/upstream_tests.patch
}

mkdir -p /logs/verifier
if restore_upstream_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_issue_478.py::TestIssue478::test_async tests/test_issue_478.py::TestIssue478::test_issue; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
