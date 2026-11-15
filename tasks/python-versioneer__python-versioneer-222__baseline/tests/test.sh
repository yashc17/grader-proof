#!/bin/bash
cd /testbed
source /opt/conda/bin/activate testbed

mkdir -p /logs/verifier
if pytest --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning test/git/test_git.py::ParseGitDescribe::test_pieces test/git/test_git.py::Keywords::test_date_gpg test/git/test_git.py::Keywords::test_date test/git/test_git.py::Keywords::test_no_prefix test/git/test_git.py::Keywords::test_no_tags test/git/test_git.py::Keywords::test_parse test/git/test_git.py::Keywords::test_prefer_short test/git/test_git.py::Keywords::test_prefix test/git/test_git.py::Keywords::test_unexpanded test/git/test_git.py::RenderPieces::test_render; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
