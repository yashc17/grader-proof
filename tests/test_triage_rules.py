import json
from pathlib import Path

from grader_proof.trajectory import Trajectory
from grader_proof.triage_rules import (
    no_network,
    own_install_failed,
    own_package_import_error,
    package_names,
    steps,
    triage,
    turn_limit,
)

FIXTURES = Path(__file__).parent / "fixtures" / "trajectories"


def load(name: str) -> Trajectory:
    return Trajectory.from_row(json.loads((FIXTURES / f"{name}.json").read_text()))


def until(trajectory: Trajectory, count: int) -> Trajectory:
    return trajectory.model_copy(update={"messages": trajectory.messages[:count]})


def with_status(trajectory: Trajectory, status: str) -> Trajectory:
    return trajectory.model_copy(update={"exit_status": status})


def test_steps_pair_each_call_with_its_observation():
    install = next(s for s in steps(load("no_network")) if "pip install" in s.command)
    assert install.failed
    assert "No matching distribution" in install.output


def test_no_network_fires_when_the_agent_never_recovers():
    # The real run passes tests right after the failed install; cut the run just before that.
    verdict = no_network(until(load("no_network"), 16))
    assert verdict is not None
    assert (verdict.rule, verdict.failure_class) == ("no_network", "env_broken")
    assert "from versions: none" in verdict.evidence


def test_no_network_abstains_when_tests_later_pass():
    assert no_network(load("no_network")) is None


def test_own_install_failed_fires():
    verdict = own_install_failed(load("install_failed"))
    assert verdict is not None
    assert verdict.failure_class == "env_broken"
    assert "pip install -e ." in verdict.evidence


def test_own_install_failed_abstains_on_a_run_without_install_failure():
    assert own_install_failed(load("normal")) is None


def test_own_package_import_error_fires():
    verdict = own_package_import_error(load("import_error"))
    assert verdict is not None
    assert verdict.failure_class == "env_broken"
    assert "No module named 'pandas._libs.pandas_parser'" in verdict.evidence


def test_own_package_import_error_abstains_for_another_package():
    other = load("import_error").model_copy(update={"repo": "someone/else"})
    assert own_package_import_error(other) is None


def test_package_names():
    assert package_names("owner/python-foo-bar") == {"python_foo_bar", "foo_bar"}
    assert package_names("owner/Foo.js") == {"foo_js"}


def test_turn_limit_fires_on_max_iterations_and_on_stuck_loops():
    for status in (
        "RuntimeError: Agent reached maximum iteration",
        "AgentStuckInLoopError: Agent got stuck in a loop",
    ):
        verdict = turn_limit(with_status(load("normal"), status))
        assert verdict is not None
        assert verdict.failure_class == "model_failure"


def test_turn_limit_abstains_on_submit():
    assert turn_limit(load("normal")) is None


def test_triage_abstains_when_no_rule_fires():
    assert triage(load("normal")) is None


def test_environment_rules_take_precedence_over_turn_limit():
    out_of_turns = with_status(
        load("install_failed"), "RuntimeError: Agent reached maximum iteration"
    )
    verdict = triage(out_of_turns)
    assert verdict is not None
    assert verdict.failure_class == "env_broken"
