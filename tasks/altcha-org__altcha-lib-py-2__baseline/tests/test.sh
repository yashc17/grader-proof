#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

mkdir -p /logs/verifier
if pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_altcha.py::TestALTCHA::test_verify_solution_expired tests/test_altcha.py::TestALTCHA::test_verify_solution_malformed_expiry tests/test_altcha.py::TestALTCHA::test_verify_solution_not_expired tests/test_altcha.py::TestALTCHA::test_create_challenge tests/test_altcha.py::TestALTCHA::test_expired_payload tests/test_altcha.py::TestALTCHA::test_hash_hex tests/test_altcha.py::TestALTCHA::test_hmac_hex tests/test_altcha.py::TestALTCHA::test_invalid_signature tests/test_altcha.py::TestALTCHA::test_solve_challenge tests/test_altcha.py::TestALTCHA::test_valid_signature tests/test_altcha.py::TestALTCHA::test_verify_solution_failure tests/test_altcha.py::TestALTCHA::test_verify_solution_success; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
