#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H3: add back the FAIL_TO_PASS tests held out of the agent's workspace.
restore_held_out_tests() {
    git apply --reverse --check /tests/held_out_tests.patch 2>/dev/null ||
        git apply /tests/held_out_tests.patch
}

mkdir -p /logs/verifier
if restore_held_out_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning 'tests/test_types_enum.py::test_enum_str_repr_in_struct[True]' 'tests/test_types_enum.py::test_enum_str_repr_in_struct[False]' 'tests/test_types_flag.py::test_flag_str_repr_in_struct[True]' 'tests/test_types_flag.py::test_flag_str_repr_in_struct[False]' 'tests/test_utils.py::test_dumpstruct_enum[True]' 'tests/test_utils.py::test_dumpstruct_enum[False]' tests/test_types_enum.py::test_enum tests/test_types_enum.py::test_enum_read tests/test_types_enum.py::test_enum_write tests/test_types_enum.py::test_enum_array_read tests/test_types_enum.py::test_enum_array_write tests/test_types_enum.py::test_enum_alias tests/test_types_enum.py::test_enum_bad_type tests/test_types_enum.py::test_enum_eof 'tests/test_types_enum.py::test_enum_same_value_different_type[True]' 'tests/test_types_enum.py::test_enum_same_value_different_type[False]' tests/test_types_enum.py::test_enum_str_repr 'tests/test_types_enum.py::test_enum_struct[True]' 'tests/test_types_enum.py::test_enum_struct[False]' tests/test_types_enum.py::test_enum_comments 'tests/test_types_enum.py::test_enum_name[True]' 'tests/test_types_enum.py::test_enum_name[False]' 'tests/test_types_enum.py::test_enum_struct_write[True]' 'tests/test_types_enum.py::test_enum_struct_write[False]' 'tests/test_types_enum.py::test_enum_anonymous[True]' 'tests/test_types_enum.py::test_enum_anonymous[False]' 'tests/test_types_enum.py::test_enum_anonymous_struct[True]' 'tests/test_types_enum.py::test_enum_anonymous_struct[False]' 'tests/test_types_enum.py::test_enum_reference_own_member[True]' 'tests/test_types_enum.py::test_enum_reference_own_member[False]' tests/test_types_flag.py::test_flag tests/test_types_flag.py::test_flag_read tests/test_types_flag.py::test_flag_write tests/test_types_flag.py::test_flag_array_read tests/test_types_flag.py::test_flag_array_write tests/test_types_flag.py::test_flag_operator tests/test_types_flag.py::test_flag_str_repr tests/test_types_flag.py::test_flag_struct 'tests/test_types_flag.py::test_flag_struct_read[True]' 'tests/test_types_flag.py::test_flag_struct_read[False]' 'tests/test_types_flag.py::test_flag_anonymous[True]' 'tests/test_types_flag.py::test_flag_anonymous[False]' 'tests/test_types_flag.py::test_flag_anonymous_struct[True]' 'tests/test_types_flag.py::test_flag_anonymous_struct[False]' tests/test_utils.py::test_hexdump 'tests/test_utils.py::test_dumpstruct[True]' 'tests/test_utils.py::test_dumpstruct[False]' 'tests/test_utils.py::test_dumpstruct_anonymous[True]' 'tests/test_utils.py::test_dumpstruct_anonymous[False]' tests/test_utils.py::test_pack_unpack tests/test_utils.py::test_swap; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
