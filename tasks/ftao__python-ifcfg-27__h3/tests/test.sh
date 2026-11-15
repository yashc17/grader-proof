#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H3: add back the FAIL_TO_PASS tests held out of the agent's workspace.
restore_held_out_tests() {
    git apply --reverse --check /tests/held_out_tests.patch 2>/dev/null ||
        git apply /tests/held_out_tests.patch
}

mkdir -p /logs/verifier
if restore_held_out_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/ifconfig_tests.py::IfcfgTestCase::test_macosx2 tests/ip_tests.py::IpTestCase::test_linux_multi_inet4 tests/ifconfig_tests.py::IfcfgTestCase::test_default_interface tests/ifconfig_tests.py::IfcfgTestCase::test_ifcfg tests/ifconfig_tests.py::IfcfgTestCase::test_illegal tests/ifconfig_tests.py::IfcfgTestCase::test_linux tests/ifconfig_tests.py::IfcfgTestCase::test_linux2 tests/ifconfig_tests.py::IfcfgTestCase::test_linux3 tests/ifconfig_tests.py::IfcfgTestCase::test_linuxdocker tests/ifconfig_tests.py::IfcfgTestCase::test_macosx tests/ifconfig_tests.py::IfcfgTestCase::test_unknown tests/ip_tests.py::IpTestCase::test_default_interface tests/ip_tests.py::IpTestCase::test_ifcfg tests/ip_tests.py::IpTestCase::test_linux; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
