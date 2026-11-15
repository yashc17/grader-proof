#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H3: add back the FAIL_TO_PASS tests held out of the agent's workspace.
restore_held_out_tests() {
    git apply --reverse --check /tests/held_out_tests.patch 2>/dev/null ||
        git apply /tests/held_out_tests.patch
}

mkdir -p /logs/verifier
if restore_held_out_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_files_to_prompt.py::test_xml_format_dir tests/test_files_to_prompt.py::test_cxml_format_multiple_paths tests/test_files_to_prompt.py::test_basic_functionality tests/test_files_to_prompt.py::test_include_hidden tests/test_files_to_prompt.py::test_ignore_gitignore tests/test_files_to_prompt.py::test_multiple_paths tests/test_files_to_prompt.py::test_ignore_patterns tests/test_files_to_prompt.py::test_mixed_paths_with_options tests/test_files_to_prompt.py::test_binary_file_warning; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
