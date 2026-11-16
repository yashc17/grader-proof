"""One client for every model call, backed by a disk cache (ADR 0004)."""

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_CACHE_DIR = Path("cache/llm")

# An upper bound on prompt tokens from the text alone, without the model's tokenizer, which is a
# download per model. ASCII is counted at 2 characters per token: over 917 cached judge prompts
# for Qwen/Qwen3.5-9B-Base (code, diffs, test names; issue #74) the lowest was 2.15 characters per
# token and the median 3.49, so the worst prompt keeps a 7% margin and a typical one is
# overcounted by about 75%. A non-ASCII character counts its UTF-8 bytes: a byte-level BPE
# tokenizer never spends more than one token per byte.
ASCII_CHARS_PER_TOKEN = 2
# The Qwen chat template adds 5 tokens per message and 3 to 5 per request (measured with the
# Qwen3-8B and Qwen3.5-9B-Base tokenizers); these allowances cover both.
CHAT_TOKENS_PER_REQUEST = 8
CHAT_TOKENS_PER_MESSAGE = 8


@dataclass(frozen=True)
class Request:
    model: str
    messages: tuple[dict[str, str], ...]
    max_tokens: int
    temperature: float
    seed: int
    prompt_version: str
    # False sends the message contents as one plain-text prompt for a base model to continue.
    chat_template: bool = True


@dataclass(frozen=True)
class Response:
    text: str
    prompt_tokens: int
    completion_tokens: int


class Transport(Protocol):
    def complete(self, request: Request) -> Response: ...


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens."""

    prefill: float
    sample: float


# Tinker list prices, dated 2026-10-19. Add a model here before estimating its cost.
PRICES: dict[str, Price] = {
    "Qwen/Qwen3-8B": Price(prefill=0.195, sample=0.60),
    "Qwen/Qwen3.5-9B-Base": Price(prefill=0.30, sample=0.807),
}


def request_key(request: Request) -> str:
    """SHA-256 of the request's canonical JSON.

    `chat_template` is left out when it has its default, so chat requests keep the keys they had
    before the field existed and their committed cache entries still match.
    """
    fields = asdict(request)
    if request.chat_template:
        del fields["chat_template"]
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class CachedClient:
    def __init__(self, transport: Transport, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
        self._transport = transport
        self._cache_dir = cache_dir

    def _path(self, request: Request) -> Path:
        return self._cache_dir / f"{request_key(request)}.json"

    def is_cached(self, request: Request) -> bool:
        return self._path(request).exists()

    def complete(self, request: Request) -> Response:
        path = self._path(request)
        if path.exists():
            return Response(**json.loads(path.read_text()))
        response = self._transport.complete(request)
        self._write_atomically(path, json.dumps(asdict(response)))
        return response

    def _write_atomically(self, path: Path, content: str) -> None:
        """Write to a temp file, then rename, so readers never see a partial entry."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=self._cache_dir, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w") as file:
                file.write(content)
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise


def max_prompt_tokens(request: Request) -> int:
    """At least as many prompt tokens as the request will use (see ASCII_CHARS_PER_TOKEN)."""
    text = "".join(message["content"] for message in request.messages)
    non_ascii = [c for c in text if not c.isascii()]
    tokens = math.ceil((len(text) - len(non_ascii)) / ASCII_CHARS_PER_TOKEN)
    tokens += sum(len(c.encode()) for c in non_ascii)
    if request.chat_template:
        tokens += CHAT_TOKENS_PER_REQUEST + CHAT_TOKENS_PER_MESSAGE * len(request.messages)
    return tokens


@dataclass(frozen=True)
class BatchEstimate:
    requests: int
    prompt_tokens: int
    completion_tokens: int
    dollars: float


def estimate_batch(client: CachedClient, requests: Sequence[Request]) -> BatchEstimate:
    """Upper-bound cost of the uncached requests.

    Prompt tokens are bounded by `max_prompt_tokens`. Completion tokens assume every
    request hits `max_tokens`. Prefill is priced at the uncached rate.
    """
    pending = [r for r in requests if not client.is_cached(r)]
    prompt_tokens = completion_tokens = 0
    dollars = 0.0
    for request in pending:
        price = PRICES[request.model]
        prompt = max_prompt_tokens(request)
        prompt_tokens += prompt
        completion_tokens += request.max_tokens
        dollars += (prompt * price.prefill + request.max_tokens * price.sample) / 1e6
    return BatchEstimate(len(pending), prompt_tokens, completion_tokens, dollars)


def ask_on_terminal() -> bool:
    return input("Run this batch? [y/N] ").strip().lower() == "y"


def run_batch(
    client: CachedClient,
    requests: Sequence[Request],
    confirm: Callable[[], bool] = ask_on_terminal,
    show: Callable[[str], None] = print,
) -> list[Response] | None:
    """Print the estimate and ask before calling the model. Returns None if declined."""
    estimate = estimate_batch(client, requests)
    if estimate.requests:
        show(
            f"{estimate.requests} of {len(requests)} requests are not cached: "
            f"up to {estimate.prompt_tokens:,} prompt tokens and up to "
            f"{estimate.completion_tokens:,} completion tokens, at most ${estimate.dollars:.2f}."
        )
        if not confirm():
            return None
    return [client.complete(r) for r in requests]
