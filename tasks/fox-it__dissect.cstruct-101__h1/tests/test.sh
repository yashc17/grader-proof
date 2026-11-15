#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H1: rewrite every file the upstream test patch touches to its upstream version.
restore_upstream_tests() {
    rm -rf -- tests/test_types_enum.py tests/test_types_flag.py tests/test_utils.py &&
        git --literal-pathspecs checkout -q 046dfa51f0989c7f55cf6d7dd00ba71f3ec5a115 -- tests/test_types_enum.py tests/test_types_flag.py tests/test_utils.py &&
        git apply /tests/upstream_tests.patch
}

mkdir -p /logs/verifier
if restore_upstream_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning 'tests/test_types_enum.py::test_enum_str_repr_in_struct[True]' 'tests/test_types_enum.py::test_enum_str_repr_in_struct[False]' 'tests/test_types_flag.py::test_flag_str_repr_in_struct[True]' 'tests/test_types_flag.py::test_flag_str_repr_in_struct[False]' 'tests/test_utils.py::test_dumpstruct_enum[True]' 'tests/test_utils.py::test_dumpstruct_enum[False]' tests/test_types_enum.py::test_enum tests/test_types_enum.py::test_enum_read tests/test_types_enum.py::test_enum_write tests/test_types_enum.py::test_enum_array_read tests/test_types_enum.py::test_enum_array_write tests/test_types_enum.py::test_enum_alias tests/test_types_enum.py::test_enum_bad_type tests/test_types_enum.py::test_enum_eof 'tests/test_types_enum.py::test_enum_same_value_different_type[True]' 'tests/test_types_enum.py::test_enum_same_value_different_type[False]' tests/test_types_enum.py::test_enum_str_repr 'tests/test_types_enum.py::test_enum_struct[True]' 'tests/test_types_enum.py::test_enum_struct[False]' tests/test_types_enum.py::test_enum_comments 'tests/test_types_enum.py::test_enum_name[True]' 'tests/test_types_enum.py::test_enum_name[False]' 'tests/test_types_enum.py::test_enum_struct_write[True]' 'tests/test_types_enum.py::test_enum_struct_write[False]' 'tests/test_types_enum.py::test_enum_anonymous[True]' 'tests/test_types_enum.py::test_enum_anonymous[False]' 'tests/test_types_enum.py::test_enum_anonymous_struct[True]' 'tests/test_types_enum.py::test_enum_anonymous_struct[False]' 'tests/test_types_enum.py::test_enum_reference_own_member[True]' 'tests/test_types_enum.py::test_enum_reference_own_member[False]' tests/test_types_flag.py::test_flag tests/test_types_flag.py::test_flag_read tests/test_types_flag.py::test_flag_write tests/test_types_flag.py::test_flag_array_read tests/test_types_flag.py::test_flag_array_write tests/test_types_flag.py::test_flag_operator tests/test_types_flag.py::test_flag_str_repr tests/test_types_flag.py::test_flag_struct 'tests/test_types_flag.py::test_flag_struct_read[True]' 'tests/test_types_flag.py::test_flag_struct_read[False]' 'tests/test_types_flag.py::test_flag_anonymous[True]' 'tests/test_types_flag.py::test_flag_anonymous[False]' 'tests/test_types_flag.py::test_flag_anonymous_struct[True]' 'tests/test_types_flag.py::test_flag_anonymous_struct[False]' tests/test_utils.py::test_hexdump 'tests/test_utils.py::test_dumpstruct[True]' 'tests/test_utils.py::test_dumpstruct[False]' 'tests/test_utils.py::test_dumpstruct_anonymous[True]' 'tests/test_utils.py::test_dumpstruct_anonymous[False]' tests/test_utils.py::test_pack_unpack tests/test_utils.py::test_swap; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
