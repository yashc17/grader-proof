#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

mkdir -p /logs/verifier
if pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_files_to_prompt.py::test_xml_format_dir tests/test_files_to_prompt.py::test_cxml_format_multiple_paths tests/test_files_to_prompt.py::test_basic_functionality tests/test_files_to_prompt.py::test_include_hidden tests/test_files_to_prompt.py::test_ignore_gitignore tests/test_files_to_prompt.py::test_multiple_paths tests/test_files_to_prompt.py::test_ignore_patterns tests/test_files_to_prompt.py::test_mixed_paths_with_options tests/test_files_to_prompt.py::test_binary_file_warning; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
