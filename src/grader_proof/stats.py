"""Agreement and interval statistics shared by every experiment."""

import random
from collections import Counter
from collections.abc import Callable, Hashable, Sequence
from math import sqrt
from statistics import NormalDist


def cohens_kappa[L: Hashable](rater_a: Sequence[L], rater_b: Sequence[L]) -> float:
    """Agreement between two raters beyond chance: (observed - chance) / (1 - chance).

    1 is perfect agreement, 0 is what chance alone gives, below 0 is worse than chance.
    When both raters use one and the same single class, chance agreement is 1 and the
    formula divides by zero. They never disagree, so the result is defined as 1.
    """
    if len(rater_a) != len(rater_b):
        raise ValueError("raters must label the same number of items (same length)")
    if not rater_a:
        raise ValueError("cannot compute kappa on empty input")

    n = len(rater_a)
    observed = sum(a == b for a, b in zip(rater_a, rater_b, strict=True)) / n
    counts_a, counts_b = Counter(rater_a), Counter(rater_b)
    chance = sum(counts_a[label] * counts_b[label] for label in counts_a) / n**2
    if chance == 1:
        return 1.0
    return (observed - chance) / (1 - chance)


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a proportion, without continuity correction."""
    if not 0 <= successes <= n or n < 1:
        raise ValueError(f"need 0 <= successes <= n and n >= 1, got successes={successes}, n={n}")

    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    p = successes / n
    scale = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / scale
    half_width = z * sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / scale
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def bootstrap_ci[T](
    values: Sequence[T],
    statistic: Callable[[Sequence[T]], float],
    *,
    seed: int,
    clusters: Sequence[Hashable] | None = None,
    n_resamples: int = 10_000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap interval for `statistic(values)`.

    Without `clusters`, items are resampled one by one. With `clusters` (one label per
    item, such as the task an instance belongs to), whole clusters are resampled with
    their items kept together. Use this when items in a cluster are correlated: it
    gives a wider, honest interval where the item bootstrap is too narrow.
    """
    if not values:
        raise ValueError("cannot bootstrap empty values")
    if clusters is not None and len(clusters) != len(values):
        raise ValueError("clusters must have one label per value")

    rng = random.Random(seed)
    if clusters is None:
        groups = [[value] for value in values]
    else:
        by_label: dict[Hashable, list[T]] = {}
        for label, value in zip(clusters, values, strict=True):
            by_label.setdefault(label, []).append(value)
        groups = list(by_label.values())

    estimates = sorted(
        statistic([value for group in rng.choices(groups, k=len(groups)) for value in group])
        for _ in range(n_resamples)
    )
    tail = (1 - confidence) / 2
    return estimates[int(tail * n_resamples)], estimates[
        min(n_resamples - 1, int((1 - tail) * n_resamples))
    ]
