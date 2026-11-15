#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H2: fail if any test file or test config differs from the base commit plus the test patch.
check_test_integrity() (
    index_dir=$(mktemp -d) &&
        export GIT_INDEX_FILE=$index_dir/index GIT_NO_REPLACE_OBJECTS=1 &&
        git read-tree fefd565a57d1b465f7112e6ac09181c2c9eb81ca &&
        git apply --cached /tests/upstream_tests.patch &&
        git diff --quiet --no-ext-diff -- ':(literal)tests/test_cli.py' ':(glob)**/conftest.py' ':(glob)**/pytest.ini' ':(glob)**/.pytest.ini' ':(glob)**/pytest.toml' ':(glob)**/.pytest.toml' ':(glob)**/setup.cfg' ':(glob)**/tox.ini' ':(glob)**/pyproject.toml' ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py' ':(glob)**/test/**' ':(glob)**/tests/**' &&
        test -z "$(git ls-files --others -- ':(literal)tests/test_cli.py' ':(glob)**/conftest.py' ':(glob)**/pytest.ini' ':(glob)**/.pytest.ini' ':(glob)**/pytest.toml' ':(glob)**/.pytest.toml' ':(glob)**/setup.cfg' ':(glob)**/tox.ini' ':(glob)**/pyproject.toml' ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py')" &&
        test -z "$(git ls-files --others -- ':(glob)**/test/**/*.py' ':(glob)**/test/**/*.pyc' ':(glob)**/test/**/*.so' ':(glob)**/tests/**/*.py' ':(glob)**/tests/**/*.pyc' ':(glob)**/tests/**/*.so' ':(exclude,glob)**/test_*.py' ':(exclude,glob)**/*_test.py' ':(exclude,glob)**/__pycache__/**')"
)

mkdir -p /logs/verifier
if check_test_integrity && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_cli.py::test_amend_requirements_content_actually_not_replacement tests/test_cli.py::test_get_package_hashes_unknown_algorithm tests/test_cli.py::test_get_latest_version_simple tests/test_cli.py::test_get_latest_version_only_pre_release tests/test_cli.py::test_get_latest_version_non_pre_release_leading_zeros tests/test_cli.py::test_get_hashes_error tests/test_cli.py::test_non_200_ok_download tests/test_cli.py::test_main_packageerrors_stderr tests/test_cli.py::test_packages_and_update_all tests/test_cli.py::test_no_packages_and_not_update_all tests/test_cli.py::test_main_version tests/test_cli.py::test_amend_requirements_content_new tests/test_cli.py::test_amend_requirements_content_multiple_merge tests/test_cli.py::test_amend_requirements_content_replacement tests/test_cli.py::test_amend_requirements_content_replacement_addition tests/test_cli.py::test_amend_requirements_content_replacement_single_to_multi tests/test_cli.py::test_amend_requirements_content_replacement_2 tests/test_cli.py::test_amend_requirements_content_replacement_amonst_others tests/test_cli.py::test_amend_requirements_content_replacement_amonst_others_2 tests/test_cli.py::test_amend_requirements_content_new_similar_name tests/test_cli.py::test_run tests/test_cli.py::test_run_atomic_not_write_with_error_on_last_package tests/test_cli.py::test_run_without_specific_version tests/test_cli.py::test_run_contained_names tests/test_cli.py::test_run_case_insensitive tests/test_cli.py::test_run_update_all tests/test_cli.py::test_run_dry tests/test_cli.py::test_run_dry_multiple_packages tests/test_cli.py::test_run_pep_0496 tests/test_cli.py::test_filter_releases tests/test_cli.py::test_release_url_metadata_python tests/test_cli.py::test_expand_python_version tests/test_cli.py::test_get_package_hashes tests/test_cli.py::test_get_package_hashes_package_not_found tests/test_cli.py::test_get_package_hashes_without_version tests/test_cli.py::test_with_extras_syntax tests/test_cli.py::test_extras_syntax_edit tests/test_cli.py::test_add_extra_extras_syntax_edit tests/test_cli.py::test_change_extra_extras_syntax_edit tests/test_cli.py::test_remove_extra_extras_syntax_edit; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
