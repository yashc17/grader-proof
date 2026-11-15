#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H3: add back the FAIL_TO_PASS tests held out of the agent's workspace.
restore_held_out_tests() {
    git apply --reverse --check /tests/held_out_tests.patch 2>/dev/null ||
        git apply /tests/held_out_tests.patch
}

mkdir -p /logs/verifier
if restore_held_out_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_issue_478.py::TestIssue478::test_async tests/test_issue_478.py::TestIssue478::test_issue; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
