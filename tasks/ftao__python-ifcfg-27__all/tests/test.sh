#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H3: add back the FAIL_TO_PASS tests held out of the agent's workspace.
restore_held_out_tests() {
    git apply --reverse --check /tests/held_out_tests.patch 2>/dev/null ||
        git apply /tests/held_out_tests.patch
}

# H2: fail if any test file or test config differs from the base commit plus the test patch.
check_test_integrity() (
    index_dir=$(mktemp -d) &&
        export GIT_INDEX_FILE=$index_dir/index GIT_NO_REPLACE_OBJECTS=1 &&
        git read-tree 3ae952775f66dc476ddb8f02953714e7676c9cff &&
        git apply --cached /tests/upstream_tests.patch &&
        git diff --quiet --no-ext-diff -- ':(literal)tests/ifconfig_out.py' ':(literal)tests/ifconfig_tests.py' ':(literal)tests/ip_out.py' ':(literal)tests/ip_tests.py' ':(glob)**/conftest.py' ':(glob)**/pytest.ini' ':(glob)**/.pytest.ini' ':(glob)**/pytest.toml' ':(glob)**/.pytest.toml' ':(glob)**/setup.cfg' ':(glob)**/tox.ini' ':(glob)**/pyproject.toml' ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py' ':(glob)**/test/**' ':(glob)**/tests/**' &&
        test -z "$(git ls-files --others -- ':(literal)tests/ifconfig_out.py' ':(literal)tests/ifconfig_tests.py' ':(literal)tests/ip_out.py' ':(literal)tests/ip_tests.py' ':(glob)**/conftest.py' ':(glob)**/pytest.ini' ':(glob)**/.pytest.ini' ':(glob)**/pytest.toml' ':(glob)**/.pytest.toml' ':(glob)**/setup.cfg' ':(glob)**/tox.ini' ':(glob)**/pyproject.toml' ':(glob)**/sitecustomize.py' ':(glob)**/usercustomize.py')" &&
        test -z "$(git ls-files --others -- ':(glob)**/test/**/*.py' ':(glob)**/test/**/*.pyc' ':(glob)**/test/**/*.so' ':(glob)**/tests/**/*.py' ':(glob)**/tests/**/*.pyc' ':(glob)**/tests/**/*.so' ':(exclude,glob)**/test_*.py' ':(exclude,glob)**/*_test.py' ':(exclude,glob)**/__pycache__/**')"
)

# H1: rewrite every file the upstream test patch touches to its upstream version.
restore_upstream_tests() {
    rm -rf -- tests/ifconfig_out.py tests/ifconfig_tests.py tests/ip_out.py tests/ip_tests.py &&
        git --literal-pathspecs checkout -q 3ae952775f66dc476ddb8f02953714e7676c9cff -- tests/ifconfig_out.py tests/ifconfig_tests.py tests/ip_out.py tests/ip_tests.py &&
        git apply /tests/upstream_tests.patch
}

mkdir -p /logs/verifier
if restore_held_out_tests && check_test_integrity && restore_upstream_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/ifconfig_tests.py::IfcfgTestCase::test_macosx2 tests/ip_tests.py::IpTestCase::test_linux_multi_inet4 tests/ifconfig_tests.py::IfcfgTestCase::test_default_interface tests/ifconfig_tests.py::IfcfgTestCase::test_ifcfg tests/ifconfig_tests.py::IfcfgTestCase::test_illegal tests/ifconfig_tests.py::IfcfgTestCase::test_linux tests/ifconfig_tests.py::IfcfgTestCase::test_linux2 tests/ifconfig_tests.py::IfcfgTestCase::test_linux3 tests/ifconfig_tests.py::IfcfgTestCase::test_linuxdocker tests/ifconfig_tests.py::IfcfgTestCase::test_macosx tests/ifconfig_tests.py::IfcfgTestCase::test_unknown tests/ip_tests.py::IpTestCase::test_default_interface tests/ip_tests.py::IpTestCase::test_ifcfg tests/ip_tests.py::IpTestCase::test_linux; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
