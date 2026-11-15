#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H3: add back the FAIL_TO_PASS tests held out of the agent's workspace.
restore_held_out_tests() {
    git apply --reverse --check /tests/held_out_tests.patch 2>/dev/null ||
        git apply /tests/held_out_tests.patch
}

mkdir -p /logs/verifier
if restore_held_out_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning test/git/test_git.py::ParseGitDescribe::test_pieces test/git/test_git.py::Keywords::test_date_gpg test/git/test_git.py::Keywords::test_date test/git/test_git.py::Keywords::test_no_prefix test/git/test_git.py::Keywords::test_no_tags test/git/test_git.py::Keywords::test_parse test/git/test_git.py::Keywords::test_prefer_short test/git/test_git.py::Keywords::test_prefix test/git/test_git.py::Keywords::test_unexpanded test/git/test_git.py::RenderPieces::test_render; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
