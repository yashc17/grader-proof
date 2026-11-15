"""Rules that assign a failure class to an unresolved trajectory, or abstain.

A rule fires only on clear evidence in what the agent ran and saw. Rules are tried in ADR 0003
precedence order, so the first rule that fires gives the class. Each verdict quotes its evidence.
The rules were tuned on the dev labels only; see `rules_eval.py`.
"""

import re
from collections.abc import Callable, Iterator, Sequence
from typing import get_args

from pydantic import BaseModel, ConfigDict

from grader_proof.labeling import FailureClass
from grader_proof.trajectory import BASH, EDITOR, Trajectory

EVIDENCE_CHARS = 200
EXIT_CODE = re.compile(r"\[The command completed with exit code (\d+)\.")
EDITOR_EDITS = {"create", "str_replace", "insert"}
EDITING_COMMAND = re.compile(r"\bsed\s+-i\b|\bgit\s+apply\b|\bcat\s*>|<<\s*['\"]?EOF")
INSTALL_COMMAND = re.compile(
    r"\b(pip3?|conda|mamba|apt(-get)?|npm|yarn)\s+install\b|\bsetup\.py\s+(install|develop)\b"
    r"|\b(curl|wget)\b|\bgit\s+(clone|fetch|pull)\b"
)
# The repository's own installation, as opposed to installing some other package.
OWN_INSTALL_COMMAND = re.compile(
    r"\bpip3?\s+install\b.*\s-e\s+\.|\bsetup\.py\s+(install|develop)\b"
)
TEST_COMMAND = re.compile(r"\bpytest\b|\bunittest\b|\btox\b")
NO_NETWORK = re.compile(
    r"Temporary failure in name resolution|Network is unreachable|Could not resolve host"
    r"|Name or service not known|Max retries exceeded|\(from versions: none\)"
    r"|Failed to establish a new connection"
)
BUILD_FAILED = re.compile(
    r"metadata-generation-failed|subprocess-exited-with-error|Failed building wheel"
    r"|Could not build wheels"
)
NO_MODULE = re.compile(r"(?:ModuleNotFoundError|ImportError): No module named '([\w.]+)'")
TURN_LIMIT_STATUSES = ("Agent reached maximum iteration", "Agent got stuck in a loop")


class Step(BaseModel):
    """One tool call paired with what came back."""

    model_config = ConfigDict(frozen=True)

    index: int  # position of the observation in the message list
    tool: str
    command: str
    output: str
    exit_code: int | None

    @property
    def failed(self) -> bool:
        return self.exit_code not in (None, 0)


class Verdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule: str
    failure_class: FailureClass
    evidence: str


Rule = Callable[[Trajectory], Verdict | None]


def steps(trajectory: Trajectory) -> list[Step]:
    """Pairs each tool call with its observation, in order."""
    pending: list[tuple[str, str]] = []
    result: list[Step] = []
    for index, message in enumerate(trajectory.messages):
        if message.role == "assistant":
            pending.extend(
                (call.name, str(call.arguments.get("command", ""))) for call in message.tool_calls
            )
        elif message.role == "tool" and pending:
            tool, command = pending.pop(0)
            code = EXIT_CODE.search(message.content)
            result.append(
                Step(
                    index=index,
                    tool=tool,
                    command=command,
                    output=message.content,
                    exit_code=int(code.group(1)) if code else None,
                )
            )
    return result


def edit_steps(trajectory: Trajectory) -> Iterator[int]:
    """Message indexes of the calls that change files."""
    for index, message in enumerate(trajectory.messages):
        for call in message.tool_calls:
            command = str(call.arguments.get("command", ""))
            if (call.name == EDITOR and command in EDITOR_EDITS) or (
                call.name == BASH and EDITING_COMMAND.search(command)
            ):
                yield index


def quote(text: str) -> str:
    return " ".join(text.split())[-EVIDENCE_CHARS:]


def recovered(later_steps: Sequence[Step]) -> bool:
    """Whether a test run passed afterwards, so the failure did not stop the agent."""
    return any(step.exit_code == 0 and TEST_COMMAND.search(step.command) for step in later_steps)


def no_network(trajectory: Trajectory) -> Verdict | None:
    """A download or install command could not reach the network and no test run passed after."""
    all_steps = steps(trajectory)
    for position, step in enumerate(all_steps):
        match = NO_NETWORK.search(step.output)
        if match is None or not (step.failed and INSTALL_COMMAND.search(step.command)):
            continue
        if not recovered(all_steps[position + 1 :]):
            return Verdict(
                rule="no_network",
                failure_class="env_broken",
                evidence=f"`{quote(step.command)}` failed: {match.group(0)}",
            )
    return None


def own_install_failed(trajectory: Trajectory) -> Verdict | None:
    """Installing the repository itself failed and no test run passed afterwards."""
    all_steps = steps(trajectory)
    for position, step in enumerate(all_steps):
        failed = step.failed and OWN_INSTALL_COMMAND.search(step.command)
        if failed and BUILD_FAILED.search(step.output) and not recovered(all_steps[position + 1 :]):
            return Verdict(
                rule="own_install_failed",
                failure_class="env_broken",
                evidence=f"`{quote(step.command)}` failed and no test run passed afterwards",
            )
    return None


def package_names(repo: str) -> set[str]:
    """Importable names the repository's own package is likely to have, from `owner/name`."""
    name = repo.split("/")[-1].lower().replace("-", "_").replace(".", "_")
    stripped = re.sub(r"^(python_|py_)|(_python|_py)$", "", name)
    return {name, stripped}


def own_package_import_error(trajectory: Trajectory) -> Verdict | None:
    """The repository's own package fails to import before any edit and the last test run too."""
    names = package_names(trajectory.repo)
    all_steps = steps(trajectory)
    first_edit = min(edit_steps(trajectory), default=len(trajectory.messages))
    test_runs = [step for step in all_steps if TEST_COMMAND.search(step.command)]
    if not test_runs:
        return None
    for step in all_steps:
        if step.index > first_edit:
            break
        for match in NO_MODULE.finditer(step.output):
            if own_module(match.group(1), names) and match.group(0) in test_runs[-1].output:
                return Verdict(
                    rule="own_package_import_error",
                    failure_class="env_broken",
                    evidence=f"before any edit and in the last test run: {match.group(0)}",
                )
    return None


def own_module(module: str, names: set[str]) -> bool:
    return module.split(".")[0].lower() in names


def turn_limit(trajectory: Trajectory) -> Verdict | None:
    """The run ended because the agent used all its turns or was stopped as stuck in a loop."""
    if any(status in trajectory.exit_status for status in TURN_LIMIT_STATUSES):
        return Verdict(
            rule="turn_limit",
            failure_class="model_failure",
            evidence=f"exit status: {quote(trajectory.exit_status)}",
        )
    return None


# ADR 0003 precedence: environment rules first.
RULES: Sequence[Rule] = (no_network, own_install_failed, own_package_import_error, turn_limit)
assert "env_broken" in get_args(FailureClass)


def triage(trajectory: Trajectory) -> Verdict | None:
    """The first rule that fires, or None when every rule abstains."""
    for rule in RULES:
        if verdict := rule(trajectory):
            return verdict
    return None
