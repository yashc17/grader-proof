#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H3: add back the FAIL_TO_PASS tests held out of the agent's workspace.
restore_held_out_tests() {
    git apply --reverse --check /tests/held_out_tests.patch 2>/dev/null ||
        git apply /tests/held_out_tests.patch
}

mkdir -p /logs/verifier
if restore_held_out_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_altcha.py::TestALTCHA::test_verify_solution_expired tests/test_altcha.py::TestALTCHA::test_verify_solution_malformed_expiry tests/test_altcha.py::TestALTCHA::test_verify_solution_not_expired tests/test_altcha.py::TestALTCHA::test_create_challenge tests/test_altcha.py::TestALTCHA::test_expired_payload tests/test_altcha.py::TestALTCHA::test_hash_hex tests/test_altcha.py::TestALTCHA::test_hmac_hex tests/test_altcha.py::TestALTCHA::test_invalid_signature tests/test_altcha.py::TestALTCHA::test_solve_challenge tests/test_altcha.py::TestALTCHA::test_valid_signature tests/test_altcha.py::TestALTCHA::test_verify_solution_failure tests/test_altcha.py::TestALTCHA::test_verify_solution_success; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
