#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H2: fail if any test file or test config differs from the base commit plus the test patch.
check_test_integrity() (
    index_dir=$(mktemp -d) &&
        export GIT_INDEX_FILE=$index_dir/index GIT_NO_REPLACE_OBJECTS=1 &&
        git read-tree 9eedc1bbaf6813c95e6b19205a0d3aadd62effd3 &&
        git apply --cached /tests/upstream_tests.patch &&
        git diff --quiet --no-ext-diff -- ':(literal)tests/test_altcha.py' ':(glob)**/conftest.py' ':(glob)**/pytest.ini' ':(glob)**/.pytest.ini' ':(glob)**/pytest.toml' ':(glob)**/.pytest.toml' ':(glob)**/setup.cfg' ':(glob)**/tox.ini' ':(glob)**/pyproject.toml' ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py' ':(glob)**/test/**' ':(glob)**/tests/**' &&
        test -z "$(git ls-files --others -- ':(literal)tests/test_altcha.py' ':(glob)**/conftest.py' ':(glob)**/pytest.ini' ':(glob)**/.pytest.ini' ':(glob)**/pytest.toml' ':(glob)**/.pytest.toml' ':(glob)**/setup.cfg' ':(glob)**/tox.ini' ':(glob)**/pyproject.toml' ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py')" &&
        test -z "$(git ls-files --others -- ':(glob)**/test/**/*.py' ':(glob)**/test/**/*.pyc' ':(glob)**/test/**/*.so' ':(glob)**/tests/**/*.py' ':(glob)**/tests/**/*.pyc' ':(glob)**/tests/**/*.so' ':(exclude,glob)**/test_*.py' ':(exclude,glob)**/*_test.py' ':(exclude,glob)**/__pycache__/**')"
)

mkdir -p /logs/verifier
if check_test_integrity && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_altcha.py::TestALTCHA::test_verify_solution_expired tests/test_altcha.py::TestALTCHA::test_verify_solution_malformed_expiry tests/test_altcha.py::TestALTCHA::test_verify_solution_not_expired tests/test_altcha.py::TestALTCHA::test_create_challenge tests/test_altcha.py::TestALTCHA::test_expired_payload tests/test_altcha.py::TestALTCHA::test_hash_hex tests/test_altcha.py::TestALTCHA::test_hmac_hex tests/test_altcha.py::TestALTCHA::test_invalid_signature tests/test_altcha.py::TestALTCHA::test_solve_challenge tests/test_altcha.py::TestALTCHA::test_valid_signature tests/test_altcha.py::TestALTCHA::test_verify_solution_failure tests/test_altcha.py::TestALTCHA::test_verify_solution_success; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
