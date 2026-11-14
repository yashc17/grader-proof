"""Ranks the instances that M2 may turn into tasks (design.md section 4, M2 selection).

Run with `make candidates`; writes results/candidates.csv and results/candidates_funnel.json.
Needs `make data-facts` (the pinned datasets), labels/sample.jsonl and the maintainer's dev labels
in labels/human.jsonl. Test-split items of the sample are never used.

Instances come from two sources, which never overlap because sample instances are excluded from
the first:
- false_positive: an unresolved trajectory whose self-check passed, on an instance outside the
  100-item sample;
- model_failure: an instance of a dev-split sample item the maintainer labeled model_failure.

An instance must pass these filters, in this order (the funnel counts the survivors of each):
1. image: the row names a prebuilt image;
2. tests: at least 2 FAIL_TO_PASS test functions, and the H3 builder can hold half of them out;
3. h2: the gold patch changes no file H2 protects;
4. network: the test patch shows no network calls, unless it also uses a mocking library;
5. size: Docker Hub knows the image, so we know its compressed size.
Ranking then takes small images, at most one instance per repository until every repository has
had a turn.
"""

import csv
import json
import random
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from grader_proof.data_facts import DATA_DIR, RESULTS_DIR
from grader_proof.h2_gold_patches import rejecting_rules
from grader_proof.held_out import function_of, hold_out
from grader_proof.labeling import LABELS_PATH, SAMPLE_PATH, read_labels, read_sample
from grader_proof.task_builder import Instance

SEED = 0
TOTAL = 20
SHARES = {"false_positive": 8 / 12, "model_failure": 4 / 12}
SIZE_CACHE = Path("cache/dockerhub")
HUB_TAG_URL = "https://hub.docker.com/v2/repositories/{image}/tags/latest"
REQUEST_PAUSE_SEC = 0.3
OUTPUT = RESULTS_DIR / "candidates.csv"
FUNNEL_OUTPUT = RESULTS_DIR / "candidates_funnel.json"

# Calls that open a connection. A bare `import requests` is not a call.
NETWORK_CALLS = re.compile(
    r"requests\.(get|post|put|delete|head|patch|request|Session)\b"
    r"|urlopen|urllib\.request|httpx\.|aiohttp|socket\.|smtplib|ftplib"
    r"|pytest\.mark\.(network|internet|remote|online)"
)
MOCKS = re.compile(r"\b(responses|requests_mock|httpretty|vcr|aioresponses|respx|mock)\b")


@dataclass(frozen=True)
class Candidate:
    instance_id: str
    repo: str
    source: str
    image: str
    size: int  # compressed bytes
    reasons: tuple[str, ...]  # why it passed: tests, h2, network, image


def network_verdict(test_patch: str) -> tuple[bool, str]:
    """Static guess from the lines the test patch adds. Mocked calls are allowed."""
    added = [
        line[1:] for line in test_patch.splitlines() if line.startswith("+") and line[:3] != "+++"
    ]
    text = "\n".join(added)
    call, mock = NETWORK_CALLS.search(text), MOCKS.search(text)
    if call and not mock:
        return False, f"test patch calls `{call.group(0)}`"
    if call and mock:
        return True, f"network calls are mocked (`{mock.group(0)}`)"
    return True, "test patch adds no network calls"


def fail_to_pass_verdict(
    instance_id: str, test_patch: str, fail_to_pass: Sequence[str]
) -> tuple[bool, str]:
    functions = {function_of(test) for test in fail_to_pass}
    if len(functions) < 2:
        return False, f"{len(functions)} FAIL_TO_PASS function"
    try:
        split = hold_out(instance_id, test_patch, fail_to_pass)
    except ValueError as error:
        return False, f"H3 cannot hold out half: {error}"
    held = len({function_of(test) for test in split.held_out})
    return True, f"{len(functions)} FAIL_TO_PASS functions; H3 holds out {held}"


def h2_verdict(row: Mapping[str, Any]) -> tuple[bool, str]:
    instance = Instance.model_construct(
        patch=row["patch"],
        test_patch=row["test_patch"],
        fail_to_pass=tuple(row["FAIL_TO_PASS"]),
        pass_to_pass=tuple(row["PASS_TO_PASS"]),
    )
    try:
        rules = rejecting_rules(instance)
    except ValueError:
        return False, "gold patch cannot be parsed"
    if rules:
        return False, f"gold patch breaks H2 rules: {sorted(rules)}"
    return True, "gold patch touches no file H2 protects"


def fetch_hub_size(image: str) -> int | None:
    """Compressed size in bytes of `image:latest`, or None if Docker Hub has no such image."""
    time.sleep(REQUEST_PAUSE_SEC)
    try:
        with urllib.request.urlopen(HUB_TAG_URL.format(image=image), timeout=30) as response:
            return int(json.load(response)["full_size"])
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def image_size(
    image: str, cache_dir: Path = SIZE_CACHE, fetch: Callable[[str], int | None] = fetch_hub_size
) -> int | None:
    """Looks in the cache first, so a rerun makes no API calls."""
    path = cache_dir / (image.replace("/", "__") + ".json")
    if path.exists():
        return json.loads(path.read_text())["size"]
    size = fetch(image)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"size": size}) + "\n")
    return size


def select(
    pool: Iterable[Candidate], total: int, shares: Mapping[str, float], seed: int
) -> list[Candidate]:
    """Picks `total` candidates, ranked. Each source gets its share of places, and a source
    that runs short hands its places to the others."""
    order = _preference_order(pool, seed)
    quotas = {source: round(total * share) for source, share in shares.items()}
    chosen = {source: order.get(source, [])[:quota] for source, quota in quotas.items()}
    spare = total - sum(map(len, chosen.values()))
    for source in shares:
        extra = order.get(source, [])[len(chosen[source]) :][:spare]
        chosen[source] += extra
        spare -= len(extra)
    ranked = [
        ((i + 0.5) / len(picks), source, c)
        for source, picks in chosen.items()
        for i, c in enumerate(picks)
    ]
    return [c for *_, c in sorted(ranked, key=lambda r: r[:2])]


def _preference_order(pool: Iterable[Candidate], seed: int) -> dict[str, list[Candidate]]:
    """Per source: first the smallest image of each repo, then the second smallest, and so on.
    Equal sizes are broken by a seeded shuffle."""
    rng = random.Random(seed)
    shuffled = sorted(pool, key=lambda c: c.instance_id)
    rng.shuffle(shuffled)
    by_source_repo: dict[str, dict[str, list[Candidate]]] = defaultdict(lambda: defaultdict(list))
    for candidate in sorted(shuffled, key=lambda c: c.size):
        by_source_repo[candidate.source][candidate.repo].append(candidate)
    order: dict[str, list[Candidate]] = {}
    for source, repos in by_source_repo.items():
        keyed = [(turn, c.size, c) for group in repos.values() for turn, c in enumerate(group)]
        order[source] = [c for *_, c in sorted(keyed, key=lambda k: k[:2])]
    return order


def read_sources() -> dict[str, str]:
    """Maps instance id to its source. Never reads the content of a test-split item."""
    if not LABELS_PATH.exists():
        raise SystemExit(
            f"{LABELS_PATH} is missing. Copy the maintainer's dev labels there; never commit it."
        )
    sample = read_sample(SAMPLE_PATH)
    dev = {item.trajectory_id: item.instance_id for item in sample if item.split == "dev"}
    sources = {
        dev[label.trajectory_id]: "model_failure"
        for label in read_labels(LABELS_PATH)
        if label.failure_class == "model_failure" and label.trajectory_id in dev
    }
    in_sample = {item.instance_id for item in sample}
    false_positives = (
        pl.scan_parquet(DATA_DIR / "trajectories/trajectories.parquet")
        .filter((pl.col("resolved") == 0) & (pl.col("pred_passes_gen_tests") == 1))
        .select("instance_id")
        .unique()
        .collect()["instance_id"]
    )
    sources.update({i: "false_positive" for i in false_positives if i not in in_sample})
    return sources


def build() -> tuple[list[Candidate], dict[str, dict[str, int]]]:
    sources = read_sources()
    rows = pl.read_parquet(
        DATA_DIR / "swe-rebench/*.parquet",
        columns=[
            "instance_id",
            "repo",
            "docker_image",
            "patch",
            "test_patch",
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
        ],
    ).filter(pl.col("instance_id").is_in(list(sources)))
    funnel: dict[str, dict[str, int]] = {}

    def count(name: str, ids: Iterable[str]) -> None:
        by_source = [sources[i] for i in ids]
        funnel[name] = {"total": len(by_source)} | {s: by_source.count(s) for s in SHARES}

    count("instances in source pools", sources)
    count("in SWE-rebench", rows["instance_id"])
    survivors: list[dict[str, Any]] = []
    reasons: dict[str, list[str]] = {}

    def keep(name: str, check: Callable[[dict[str, Any]], tuple[bool, str]]) -> None:
        nonlocal survivors
        kept: list[dict[str, Any]] = []
        for row in survivors:
            passed, reason = check(row)
            if passed:
                reasons[row["instance_id"]].append(reason)
                kept.append(row)
        survivors = kept
        count(name, (r["instance_id"] for r in survivors))

    survivors = [r for r in rows.iter_rows(named=True) if r["docker_image"]]
    reasons = {r["instance_id"]: list[str]() for r in survivors}
    count("has a prebuilt image", (r["instance_id"] for r in survivors))
    keep(
        "2+ FAIL_TO_PASS functions, H3 holds out half",
        lambda r: fail_to_pass_verdict(r["instance_id"], r["test_patch"], r["FAIL_TO_PASS"]),
    )
    keep("gold patch touches no H2-protected file", h2_verdict)
    keep("no network calls in test patch", lambda r: network_verdict(r["test_patch"]))

    pool: list[Candidate] = []
    for row in survivors:
        size = image_size(row["docker_image"])
        if size is None:
            continue
        pool.append(
            Candidate(
                instance_id=row["instance_id"],
                repo=row["repo"],
                source=sources[row["instance_id"]],
                image=row["docker_image"],
                size=size,
                reasons=(*reasons[row["instance_id"]], f"{size / 1e9:.2f} GB compressed"),
            )
        )
    count("image found on Docker Hub", (c.instance_id for c in pool))
    funnel["repositories in the final pool"] = {"total": len({c.repo for c in pool})}
    return select(pool, TOTAL, SHARES, SEED), funnel


def main() -> None:
    chosen, funnel = build()
    RESULTS_DIR.mkdir(exist_ok=True)
    columns = ["rank", "instance_id", "repo", "source", "image", "image_gb"]
    columns += ["why_tests", "why_h2", "why_network", "why_image"]
    with OUTPUT.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        for rank, c in enumerate(chosen, 1):
            row = [rank, c.instance_id, c.repo, c.source, c.image, f"{c.size / 1e9:.2f}"]
            writer.writerow([*row, *c.reasons])
    FUNNEL_OUTPUT.write_text(json.dumps(funnel, indent=2) + "\n")
    print(json.dumps(funnel, indent=2))
    for rank, c in enumerate(chosen, 1):
        print(f"{rank:2} {c.source:14} {c.size / 1e9:5.2f} GB  {c.instance_id}")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
