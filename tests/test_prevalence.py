import pytest

from grader_proof.labeling import Candidate
from grader_proof.prevalence import class_shares, draw_prevalence_sample


def candidates(n: int) -> list[Candidate]:
    return [
        Candidate(trajectory_id=f"t{i:03d}", instance_id=f"i{i // 3}", self_check_passed=None)
        for i in range(n)
    ]


def test_draw_skips_the_labeled_sample_and_is_fixed_by_the_seed():
    pool = candidates(300)
    labeled = {f"t{i:03d}" for i in range(0, 300, 2)}
    drawn = draw_prevalence_sample(pool, labeled, seed=1, size=100)
    assert len(drawn) == len({c.trajectory_id for c in drawn}) == 100
    assert not {c.trajectory_id for c in drawn} & labeled
    assert drawn == draw_prevalence_sample(list(reversed(pool)), labeled, seed=1, size=100)
    assert drawn != draw_prevalence_sample(pool, labeled, seed=2, size=100)


def test_draw_refuses_a_pool_smaller_than_the_size():
    with pytest.raises(ValueError, match="only 5"):
        draw_prevalence_sample(candidates(10), {f"t{i:03d}" for i in range(5)}, seed=1, size=6)


def test_class_shares_count_every_class_with_an_interval_around_the_share():
    classes = ["model_failure"] * 6 + ["env_broken"] * 3 + ["unclear"]
    instances = [f"i{i // 2}" for i in range(10)]
    shares = class_shares(classes, instances)
    assert list(shares) == [
        "env_broken",
        "task_underspecified",
        "upstream_tests_wrong",
        "model_failure",
        "unclear",
    ]
    model_failure = shares["model_failure"]
    assert (model_failure.count, model_failure.share) == (6, pytest.approx(0.6))
    assert model_failure.low <= 0.6 <= model_failure.high
    assert shares["task_underspecified"].count == 0
    assert shares["task_underspecified"].high == 0


def test_class_shares_resample_whole_instances():
    """Two instances, each with all its trajectories in one class: a resample can hold only
    one of them, so the interval spans 0 to 1, wider than an item bootstrap would give."""
    classes = ["model_failure"] * 50 + ["env_broken"] * 50
    instances = ["a"] * 50 + ["b"] * 50
    share = class_shares(classes, instances)["model_failure"]
    assert (share.low, share.high) == (0, 1)
