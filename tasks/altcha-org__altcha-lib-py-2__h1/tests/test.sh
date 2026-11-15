#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H1: rewrite every file the upstream test patch touches to its upstream version.
restore_upstream_tests() {
    rm -rf -- tests/test_altcha.py &&
        git --literal-pathspecs checkout -q 9eedc1bbaf6813c95e6b19205a0d3aadd62effd3 -- tests/test_altcha.py &&
        git apply /tests/upstream_tests.patch
}

mkdir -p /logs/verifier
if restore_upstream_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_altcha.py::TestALTCHA::test_verify_solution_expired tests/test_altcha.py::TestALTCHA::test_verify_solution_malformed_expiry tests/test_altcha.py::TestALTCHA::test_verify_solution_not_expired tests/test_altcha.py::TestALTCHA::test_create_challenge tests/test_altcha.py::TestALTCHA::test_expired_payload tests/test_altcha.py::TestALTCHA::test_hash_hex tests/test_altcha.py::TestALTCHA::test_hmac_hex tests/test_altcha.py::TestALTCHA::test_invalid_signature tests/test_altcha.py::TestALTCHA::test_solve_challenge tests/test_altcha.py::TestALTCHA::test_valid_signature tests/test_altcha.py::TestALTCHA::test_verify_solution_failure tests/test_altcha.py::TestALTCHA::test_verify_solution_success; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
