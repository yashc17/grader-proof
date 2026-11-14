"""One client for every model call, backed by a disk cache (ADR 0004)."""

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_CACHE_DIR = Path("cache/llm")
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class Request:
    model: str
    messages: tuple[dict[str, str], ...]
    max_tokens: int
    temperature: float
    seed: int
    prompt_version: str


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
}


def request_key(request: Request) -> str:
    canonical = json.dumps(asdict(request), sort_keys=True, separators=(",", ":"))
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


@dataclass(frozen=True)
class BatchEstimate:
    requests: int
    prompt_tokens: int
    completion_tokens: int
    dollars: float


def estimate_batch(client: CachedClient, requests: Sequence[Request]) -> BatchEstimate:
    """Upper-bound cost of the uncached requests.

    Prompt tokens are estimated from text length. Completion tokens assume every
    request hits `max_tokens`. Prefill is priced at the uncached rate.
    """
    pending = [r for r in requests if not client.is_cached(r)]
    prompt_tokens = completion_tokens = 0
    dollars = 0.0
    for request in pending:
        price = PRICES[request.model]
        prompt = sum(len(m["content"]) for m in request.messages) // CHARS_PER_TOKEN
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
            f"about {estimate.prompt_tokens:,} prompt tokens and up to "
            f"{estimate.completion_tokens:,} completion tokens, at most ${estimate.dollars:.2f}."
        )
        if not confirm():
            return None
    return [client.complete(r) for r in requests]
