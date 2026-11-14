import random
from collections.abc import Sequence

import pytest

from grader_proof.stats import bootstrap_ci, cohens_kappa, wilson_interval


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


class TestCohensKappa:
    def test_perfect_agreement(self):
        assert cohens_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0

    def test_agreement_at_chance_level(self):
        # Observed agreement 2/4, chance agreement 0.5 * 0.5 + 0.5 * 0.5 = 0.5.
        assert cohens_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == 0.0

    def test_complete_disagreement(self):
        assert cohens_kappa([1, 0], [0, 1]) == -1.0

    def test_two_classes(self):
        # Observed 3/4. Chance 0.5 * 0.25 + 0.5 * 0.75 = 0.5. Kappa (0.75 - 0.5) / 0.5.
        assert cohens_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(0.5)

    def test_three_classes_with_string_labels(self):
        # Observed 3/4. Chance 0.5 * 0.25 + 0.25 * 0.5 + 0.25 * 0.25 = 0.3125.
        # Kappa (0.75 - 0.3125) / (1 - 0.3125) = 7 / 11.
        a = ["x", "x", "y", "z"]
        b = ["x", "y", "y", "z"]
        assert cohens_kappa(a, b) == pytest.approx(7 / 11)

    def test_single_class_counts_as_perfect_agreement(self):
        # Chance agreement is 1, so the formula divides by zero. Both raters never
        # disagree, so the result is defined as 1.
        assert cohens_kappa(["a", "a", "a"], ["a", "a", "a"]) == 1.0

    def test_rejects_unequal_lengths(self):
        with pytest.raises(ValueError, match="same length"):
            cohens_kappa([1, 0], [1])

    def test_rejects_empty_input(self):
        with pytest.raises(ValueError, match="empty"):
            cohens_kappa([], [])


class TestWilsonInterval:
    # Reference values: Newcombe (1998), "Two-sided confidence intervals for the single
    # proportion: comparison of seven methods", Statistics in Medicine 17:857-872,
    # Table I, method 3 (score method without continuity correction), 95% intervals.
    @pytest.mark.parametrize(
        ("successes", "n", "lower", "upper"),
        [
            (81, 263, 0.2553, 0.3662),
            (15, 148, 0.0624, 0.1605),
            (0, 20, 0.0000, 0.1611),
            (1, 29, 0.0061, 0.1718),
        ],
    )
    def test_matches_newcombe_table_1(self, successes: int, n: int, lower: float, upper: float):
        got_lower, got_upper = wilson_interval(successes, n)
        assert got_lower == pytest.approx(lower, abs=5e-5)
        assert got_upper == pytest.approx(upper, abs=5e-5)

    def test_stays_inside_zero_and_one(self):
        assert wilson_interval(0, 5)[0] == 0.0
        assert wilson_interval(5, 5)[1] == 1.0

    def test_higher_confidence_gives_wider_interval(self):
        narrow = wilson_interval(10, 40, confidence=0.90)
        wide = wilson_interval(10, 40, confidence=0.99)
        assert wide[0] < narrow[0]
        assert narrow[1] < wide[1]

    @pytest.mark.parametrize(("successes", "n"), [(1, 0), (-1, 5), (6, 5)])
    def test_rejects_invalid_counts(self, successes: int, n: int):
        with pytest.raises(ValueError, match="successes"):
            wilson_interval(successes, n)


class TestBootstrapCi:
    def test_same_seed_gives_same_interval(self):
        values = [1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0]
        first = bootstrap_ci(values, mean, seed=7)
        second = bootstrap_ci(values, mean, seed=7)
        assert first == second

    def test_different_seeds_give_different_intervals(self):
        rng = random.Random(0)
        values = [rng.random() for _ in range(30)]
        assert bootstrap_ci(values, mean, seed=1) != bootstrap_ci(values, mean, seed=2)

    def test_interval_contains_the_point_estimate(self):
        values = [float(i) for i in range(50)]
        lower, upper = bootstrap_ci(values, mean, seed=0)
        assert lower < mean(values) < upper

    def test_constant_data_gives_zero_width_interval(self):
        assert bootstrap_ci([3.0] * 10, mean, seed=0) == (3.0, 3.0)

    def test_clusters_are_resampled_whole(self):
        # Cluster c holds c + 1 items, so a sample is made of whole clusters only if
        # each cluster's item count is a multiple of its size.
        items = [(c, i) for c in range(6) for i in range(c + 1)]
        clusters = [c for c, _ in items]
        seen: list[Sequence[tuple[int, int]]] = []

        def record(sample: Sequence[tuple[int, int]]) -> float:
            seen.append(sample)
            return 0.0

        bootstrap_ci(items, record, clusters=clusters, n_resamples=200, seed=3)

        assert len(seen) == 200
        for sample in seen:
            for c in range(6):
                members = [item for item in sample if item[0] == c]
                assert len(members) % (c + 1) == 0
                assert set(members) <= {(c, i) for i in range(c + 1)}

    def test_cluster_interval_is_wider_when_items_in_a_cluster_agree(self):
        # 20 clusters of 10 items. Every item in a cluster has the same value, so the
        # data holds 20 independent observations, not 200.
        rng = random.Random(0)
        cluster_values = [float(rng.random() < 0.5) for _ in range(20)]
        values = [v for v in cluster_values for _ in range(10)]
        clusters = [c for c in range(20) for _ in range(10)]

        item_lower, item_upper = bootstrap_ci(values, mean, seed=1)
        cluster_lower, cluster_upper = bootstrap_ci(values, mean, clusters=clusters, seed=1)

        assert (cluster_upper - cluster_lower) > 2 * (item_upper - item_lower)

    def test_clustered_bootstrap_is_reproducible(self):
        values = [float(i % 3) for i in range(30)]
        clusters = [i // 5 for i in range(30)]
        first = bootstrap_ci(values, mean, clusters=clusters, seed=11)
        assert first == bootstrap_ci(values, mean, clusters=clusters, seed=11)

    def test_rejects_mismatched_clusters(self):
        with pytest.raises(ValueError, match="clusters"):
            bootstrap_ci([1.0, 2.0], mean, clusters=[0], seed=0)

    def test_rejects_empty_values(self):
        with pytest.raises(ValueError, match="empty"):
            bootstrap_ci([], mean, seed=0)
