import hashlib
import json
from pathlib import Path

import pytest

from grader_proof.llm import (
    CachedClient,
    Request,
    Response,
    estimate_batch,
    max_prompt_tokens,
    request_key,
    run_batch,
)

QWEN = "Qwen/Qwen3-8B"


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[Request] = []

    def complete(self, request: Request) -> Response:
        self.calls.append(request)
        return Response(text="ok", prompt_tokens=10, completion_tokens=2)


def make_request(**changes: object) -> Request:
    fields: dict[str, object] = {
        "model": QWEN,
        "messages": ({"role": "user", "content": "hi"},),
        "max_tokens": 100,
        "temperature": 0.0,
        "seed": 0,
        "prompt_version": "judge-v1",
    }
    return Request(**{**fields, **changes})  # type: ignore[arg-type]


def test_second_identical_request_makes_no_call(tmp_path: Path) -> None:
    transport = FakeTransport()
    client = CachedClient(transport, tmp_path)
    first = client.complete(make_request())
    second = client.complete(make_request())
    assert first == second
    assert len(transport.calls) == 1


def test_cache_survives_a_new_client(tmp_path: Path) -> None:
    CachedClient(FakeTransport(), tmp_path).complete(make_request())
    transport = FakeTransport()
    CachedClient(transport, tmp_path).complete(make_request())
    assert transport.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"model": "other/model"},
        {"messages": ({"role": "user", "content": "hi!"},)},
        {"messages": ({"role": "system", "content": "hi"},)},
        {"max_tokens": 101},
        {"temperature": 0.5},
        {"seed": 1},
        {"prompt_version": "judge-v2"},
        {"chat_template": False},
    ],
)
def test_any_change_to_the_request_changes_the_key(change: dict[str, object]) -> None:
    assert request_key(make_request()) != request_key(make_request(**change))


def test_chat_requests_keep_the_key_they_had_before_chat_template_existed() -> None:
    fields = {
        "model": QWEN,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 100,
        "temperature": 0.0,
        "seed": 0,
        "prompt_version": "judge-v1",
    }
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    assert request_key(make_request()) == hashlib.sha256(canonical.encode()).hexdigest()


def test_key_is_a_sha256_hex_digest() -> None:
    key = request_key(make_request())
    assert len(key) == 64
    assert key == request_key(make_request())


def test_entry_is_one_json_file_named_by_key_and_leaves_no_temp_files(tmp_path: Path) -> None:
    request = make_request()
    CachedClient(FakeTransport(), tmp_path).complete(request)
    files = list(tmp_path.iterdir())
    assert [f.name for f in files] == [f"{request_key(request)}.json"]
    assert json.loads(files[0].read_text())["text"] == "ok"


def test_failed_call_writes_nothing(tmp_path: Path) -> None:
    class Failing:
        def complete(self, request: Request) -> Response:
            raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        CachedClient(Failing(), tmp_path).complete(make_request())
    assert list(tmp_path.iterdir()) == []


def test_estimate_counts_only_uncached_requests(tmp_path: Path) -> None:
    client = CachedClient(FakeTransport(), tmp_path)
    cached = make_request()
    fresh = make_request(messages=({"role": "user", "content": "x" * 400},))
    client.complete(cached)
    estimate = estimate_batch(client, [cached, fresh])
    assert estimate.requests == 1
    assert estimate.prompt_tokens == 216  # 400 characters at 2 per token, plus the chat template
    assert estimate.completion_tokens == 100  # max_tokens is the upper bound
    expected = 216 * 0.195 / 1e6 + 100 * 0.60 / 1e6
    assert estimate.dollars == pytest.approx(expected)


def test_estimate_bounds_the_worst_cached_judge_prompt(tmp_path: Path) -> None:
    """Issue #74: a 24,246-character ASCII judge prompt used 11,299 prompt tokens."""
    client = CachedClient(FakeTransport(), tmp_path)
    worst = make_request(messages=({"role": "user", "content": "x" * 24_246},), chat_template=False)
    assert estimate_batch(client, [worst]).prompt_tokens >= 11_299


def test_prompt_bound_counts_ascii_at_two_characters_and_other_text_by_utf8_bytes() -> None:
    assert (
        max_prompt_tokens(
            make_request(messages=({"role": "user", "content": "abcde"},), chat_template=False)
        )
        == 3
    )
    # "é" is 2 UTF-8 bytes and "中" is 3: a byte-level tokenizer spends at most one token per byte.
    assert (
        max_prompt_tokens(
            make_request(messages=({"role": "user", "content": "é中"},), chat_template=False)
        )
        == 5
    )


def test_prompt_bound_adds_the_chat_template_only_for_chat_requests() -> None:
    two = ({"role": "system", "content": ""}, {"role": "user", "content": ""})
    assert max_prompt_tokens(make_request(messages=two, chat_template=False)) == 0
    assert max_prompt_tokens(make_request(messages=two)) == 24


def test_estimate_rejects_a_model_without_a_price(tmp_path: Path) -> None:
    client = CachedClient(FakeTransport(), tmp_path)
    with pytest.raises(KeyError, match="other/model"):
        estimate_batch(client, [make_request(model="other/model")])


def test_batch_asks_before_calling_and_declining_makes_no_call(tmp_path: Path) -> None:
    transport = FakeTransport()
    client = CachedClient(transport, tmp_path)
    shown: list[str] = []
    result = run_batch(client, [make_request()], confirm=lambda: False, show=shown.append)
    assert result is None
    assert transport.calls == []
    assert "tokens" in shown[0]
    assert "$" in shown[0]


def test_confirmed_batch_returns_responses_in_order(tmp_path: Path) -> None:
    transport = FakeTransport()
    client = CachedClient(transport, tmp_path)
    requests = [make_request(seed=i) for i in range(3)]
    result = run_batch(client, requests, confirm=lambda: True, show=lambda _: None)
    assert result is not None
    assert len(result) == 3
    assert transport.calls == requests


def test_fully_cached_batch_does_not_ask(tmp_path: Path) -> None:
    client = CachedClient(FakeTransport(), tmp_path)
    client.complete(make_request())

    def refuse() -> bool:
        raise AssertionError("should not ask")

    result = run_batch(client, [make_request()], confirm=refuse, show=lambda _: None)
    assert result is not None
    assert len(result) == 1
