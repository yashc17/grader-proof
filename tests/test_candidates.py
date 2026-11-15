import json

import pytest

from grader_proof.candidates import (
    Candidate,
    fail_to_pass_verdict,
    image_size,
    network_verdict,
    select,
)

TEST_PATCH = """\
diff --git a/tests/test_x.py b/tests/test_x.py
index 1111111..2222222 100644
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1,3 +1,11 @@
 import pytest

+
+def test_a():
+    assert 1 == 1
+
+
+def test_b():
+    assert 2 == 2
+
 x = 1
"""


def added(line: str) -> str:
    return f"+++ b/tests/test_x.py\n@@ -1 +1,2 @@\n x\n+{line}\n"


@pytest.mark.parametrize(
    ("line", "passes"),
    [
        ("assert add(1, 2) == 3", True),
        ("url = 'https://api.example.org/v1'", True),
        ("r = requests.get('http://x.test')", False),
        ("with urllib.request.urlopen(url) as f:", False),
        ("s = socket.create_connection(('a', 1))", False),
        ("@pytest.mark.network", False),
        ("r = requests.get(url)  # responses.add is used above", True),
    ],
)
def test_network_heuristic(line, passes):
    assert network_verdict(added(line))[0] is passes


def test_network_ignores_removed_and_context_lines():
    patch = "@@ -1,2 +1,1 @@\n-requests.get(u)\n requests.post(u)\n+ok = 1\n"
    assert network_verdict(patch)[0] is True


def test_mocked_network_passes_with_a_reason():
    patch = added("import responses") + added("requests.get(u)")
    passes, reason = network_verdict(patch)
    assert passes
    assert "mock" in reason


def test_tests_filter_needs_two_functions():
    one = ["tests/test_x.py::test_a", "tests/test_x.py::test_a[1]", "tests/test_x.py::test_a[2]"]
    passes, reason = fail_to_pass_verdict("i", TEST_PATCH, one)
    assert not passes
    assert "1 FAIL_TO_PASS function" in reason


def test_tests_filter_counts_functions_and_checks_hold_out():
    passes, reason = fail_to_pass_verdict(
        "i", TEST_PATCH, ["tests/test_x.py::test_a", "tests/test_x.py::test_b[p]"]
    )
    assert passes
    assert "2 FAIL_TO_PASS functions" in reason
    assert "holds out 1" in reason


def test_tests_filter_rejects_when_hold_out_refuses():
    passes, reason = fail_to_pass_verdict(
        "i", TEST_PATCH, ["tests/test_x.py::test_p", "tests/test_x.py::test_q"]
    )
    assert not passes
    assert "H3" in reason


def test_image_size_is_fetched_once_then_cached(tmp_path):
    calls = []

    def fetch(image: str) -> int | None:
        calls.append(image)
        return 123

    assert image_size("o/img", tmp_path, fetch) == 123
    assert image_size("o/img", tmp_path, fetch) == 123
    assert calls == ["o/img"]
    assert json.loads(next(tmp_path.iterdir()).read_text()) == {"size": 123}


def test_missing_image_is_cached_as_none(tmp_path):
    calls = []

    def fetch(image: str) -> int | None:
        calls.append(image)

    assert image_size("o/img", tmp_path, fetch) is None
    assert image_size("o/img", tmp_path, fetch) is None
    assert len(calls) == 1


def cand(instance: str, repo: str, size: int, source: str = "false_positive") -> Candidate:
    return Candidate(
        instance_id=instance,
        repo=repo,
        source=source,
        image=f"img/{instance}",
        size=size,
        reasons=("a", "b", "c", "d"),
    )


def test_select_prefers_new_repos_before_small_images():
    pool = [cand("a1", "A", 1), cand("a2", "A", 2), cand("a3", "A", 3), cand("b1", "B", 900)]
    chosen = select(pool, total=2, shares={"false_positive": 1.0}, seed=0)
    assert {c.instance_id for c in chosen} == {"a1", "b1"}


def test_select_within_a_repo_takes_the_smallest():
    pool = [cand("a3", "A", 3), cand("a1", "A", 1), cand("a2", "A", 2)]
    chosen = select(pool, total=2, shares={"false_positive": 1.0}, seed=0)
    assert {c.instance_id for c in chosen} == {"a1", "a2"}


def test_select_respects_shares_and_fills_a_short_source():
    pool = [cand(f"f{i}", f"R{i}", i) for i in range(6)]
    pool += [cand(f"m{i}", f"S{i}", i, "model_failure") for i in range(2)]
    chosen = select(pool, total=6, shares={"false_positive": 2 / 3, "model_failure": 1 / 3}, seed=0)
    sources = [c.source for c in chosen]
    assert sources.count("model_failure") == 2
    assert sources.count("false_positive") == 4
    short = select(
        pool[:6] + pool[6:7], total=6, shares={"false_positive": 0.5, "model_failure": 0.5}, seed=0
    )
    assert [c.source for c in short].count("false_positive") == 5


def test_select_is_seeded():
    pool = [cand(f"i{i}", f"R{i}", 5) for i in range(10)]
    shares = {"false_positive": 1.0}
    first = select(pool, total=4, shares=shares, seed=1)
    assert first == select(pool, total=4, shares=shares, seed=1)
    assert first != select(pool, total=4, shares=shares, seed=2)


def test_select_ranks_by_interleaving_sources():
    pool = [cand(f"f{i}", f"R{i}", i) for i in range(4)]
    pool += [cand(f"m{i}", f"S{i}", i, "model_failure") for i in range(2)]
    chosen = select(pool, total=6, shares={"false_positive": 2 / 3, "model_failure": 1 / 3}, seed=0)
    assert [c.source for c in chosen][:3].count("model_failure") == 1
