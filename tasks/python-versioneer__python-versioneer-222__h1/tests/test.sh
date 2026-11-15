#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

# H1: rewrite every file the upstream test patch touches to its upstream version.
restore_upstream_tests() {
    rm -rf -- test/git/test_git.py &&
        git --literal-pathspecs checkout -q c8d014eecac6ef4b77c47310830d8837a1c61d55 -- test/git/test_git.py &&
        git apply /tests/upstream_tests.patch
}

mkdir -p /logs/verifier
if restore_upstream_tests && pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning test/git/test_git.py::ParseGitDescribe::test_pieces test/git/test_git.py::Keywords::test_date_gpg test/git/test_git.py::Keywords::test_date test/git/test_git.py::Keywords::test_no_prefix test/git/test_git.py::Keywords::test_no_tags test/git/test_git.py::Keywords::test_parse test/git/test_git.py::Keywords::test_prefer_short test/git/test_git.py::Keywords::test_prefix test/git/test_git.py::Keywords::test_unexpanded test/git/test_git.py::RenderPieces::test_render; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
