#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H1: rewrite every file the upstream test patch touches to its upstream version.
restore_upstream_tests() {
    rm -rf -- tests/ifconfig_out.py tests/ifconfig_tests.py tests/ip_out.py tests/ip_tests.py &&
        git --literal-pathspecs checkout -q 3ae952775f66dc476ddb8f02953714e7676c9cff -- tests/ifconfig_out.py tests/ifconfig_tests.py tests/ip_out.py tests/ip_tests.py &&
        git apply /tests/upstream_tests.patch
}

mkdir -p /logs/verifier
if restore_upstream_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/ifconfig_tests.py::IfcfgTestCase::test_macosx2 tests/ip_tests.py::IpTestCase::test_linux_multi_inet4 tests/ifconfig_tests.py::IfcfgTestCase::test_default_interface tests/ifconfig_tests.py::IfcfgTestCase::test_ifcfg tests/ifconfig_tests.py::IfcfgTestCase::test_illegal tests/ifconfig_tests.py::IfcfgTestCase::test_linux tests/ifconfig_tests.py::IfcfgTestCase::test_linux2 tests/ifconfig_tests.py::IfcfgTestCase::test_linux3 tests/ifconfig_tests.py::IfcfgTestCase::test_linuxdocker tests/ifconfig_tests.py::IfcfgTestCase::test_macosx tests/ifconfig_tests.py::IfcfgTestCase::test_unknown tests/ip_tests.py::IpTestCase::test_default_interface tests/ip_tests.py::IpTestCase::test_ifcfg tests/ip_tests.py::IpTestCase::test_linux; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
