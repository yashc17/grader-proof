"""The LLM judge: assigns a failure class to an unresolved trajectory that every rule abstains on.

The judge model is a base model, so each prompt is a document for it to continue: a short casebook
of hand-written cases that ends where the verdict JSON of the case at hand should start. Prompts
are versioned text files in `judge_prompts/`; the version is part of every cache key (ADR 0004).
They are tuned on the dev labels only (see `judge_eval.py`), and `FROZEN_VERSION` is the one the
test-set run uses.
"""

import json
import re
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from grader_proof.labeling import FailureClass
from grader_proof.llm import CachedClient, Request, Response, ask_on_terminal, run_batch
from grader_proof.trajectory import CHARS_PER_TOKEN, Trajectory, clip, condense

JUDGE_MODEL = "Qwen/Qwen3.5-9B-Base"
PROMPTS_DIR = Path(__file__).parent / "judge_prompts"
FROZEN_VERSION = "judge-v1"
FROZEN_SHA256 = "f28c62842fcc613d1d6e0a87908a529dae8b87b21605dbb7027262f4a7332ecd"

MAX_TOKENS = 300
SEED = 0
# With the 4,000-token condensed trajectory this keeps a case under about 9,000 tokens.
ISSUE_CHARS = 1500 * CHARS_PER_TOKEN
GOLD_PATCH_CHARS = 1500 * CHARS_PER_TOKEN
AGENT_PATCH_CHARS = 2000 * CHARS_PER_TOKEN
MAX_TEST_NAMES = 30
MAX_OMITTED_NAMES = 20
REPAIR_INPUT_CHARS = 2000

PLACEHOLDERS = ("issue", "fail_to_pass", "gold_patch", "agent_patch", "trajectory")
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
FILE_START = re.compile(r"^(?=diff --git )", re.MULTILINE)
DIFF_PATH = re.compile(r"^diff --git a/.+ b/(.+)")
REPAIR_TEMPLATE = """\
The text below was meant to be one JSON object with exactly three keys: "evidence" (a string), \
"failure_class" (one of "env_broken", "task_underspecified", "upstream_tests_wrong", \
"model_failure", "unclear") and "confidence" (a number from 0 to 1). It could not be read: {error}

Text:
{text}

The same verdict as one valid JSON object, on one line:
"""


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class JudgeInput(Frozen):
    """What the judge sees of one trajectory, already cut to its token budget."""

    issue: str
    fail_to_pass: tuple[str, ...]
    gold_patch: str
    agent_patch: str
    trajectory: str


class JudgeVerdict(Frozen):
    evidence: str
    failure_class: FailureClass
    confidence: float = Field(ge=0, le=1)


Outcome = Literal["parsed", "repaired", "failed"]


class JudgeResult(Frozen):
    """`failed` means neither the answer nor its repair parsed; the verdict is then `unclear`."""

    verdict: JudgeVerdict
    outcome: Outcome
    prompt_tokens: int
    completion_tokens: int


class Prompt(Frozen):
    version: str
    text: str


UNREADABLE = JudgeVerdict(evidence="", failure_class="unclear", confidence=0)


def prompt_versions() -> list[str]:
    return sorted(path.stem for path in PROMPTS_DIR.glob("*.txt"))


def load_prompt(version: str) -> Prompt:
    return Prompt(version=version, text=(PROMPTS_DIR / f"{version}.txt").read_text())


def judge_input(
    trajectory: Trajectory, issue: str, gold_patch: str, fail_to_pass: Sequence[str]
) -> JudgeInput:
    names = list(fail_to_pass[:MAX_TEST_NAMES])
    if len(fail_to_pass) > MAX_TEST_NAMES:
        names.append(f"... {len(fail_to_pass) - MAX_TEST_NAMES} more")
    gold_files = {path for path, _ in file_sections(gold_patch)}
    return JudgeInput(
        issue=clip(issue.strip(), ISSUE_CHARS),
        fail_to_pass=tuple(names),
        gold_patch=patch_view(gold_patch, GOLD_PATCH_CHARS),
        agent_patch=patch_view(trajectory.model_patch, AGENT_PATCH_CHARS, gold_files) or "(empty)",
        trajectory=condense(trajectory).text,
    )


def file_sections(patch: str) -> list[tuple[str, str]]:
    """Splits a git diff into (path, text) for each file it changes."""
    sections: list[tuple[str, str]] = []
    for chunk in FILE_START.split(patch):
        if header := DIFF_PATH.match(chunk):
            sections.append((header.group(1), chunk.strip("\n")))
    return sections


def is_hidden_or_cache(path: str) -> bool:
    parts = path.split("/")
    hidden = any(part.startswith(".") or part == "__pycache__" for part in parts)
    return hidden or path.endswith(".pyc")


def patch_view(patch: str, budget_chars: int, first: Collection[str] = ()) -> str:
    """The patch cut to the budget, with the most telling files first.

    Files in `first` come first and hidden or cache files (such as `.hypothesis/`) last. The file
    at the cut is shown in part; the files after it are listed by name.
    """
    sections = file_sections(patch)
    if not sections:
        return clip(patch.strip(), budget_chars)
    sections.sort(key=lambda section: (section[0] not in first, is_hidden_or_cache(section[0])))
    shown = clip("\n".join(text for _, text in sections), budget_chars)
    omitted = [path for path, text in sections if text.splitlines()[0] not in shown]
    if not omitted:
        return shown
    names = ", ".join(omitted[:MAX_OMITTED_NAMES])
    if len(omitted) > MAX_OMITTED_NAMES:
        names += ", ..."
    noun = "file" if len(omitted) == 1 else "files"
    return f"{shown}\n... {len(omitted)} more {noun} not shown: {names}"


def render(template: str, judge_input: JudgeInput) -> str:
    """Fills each {{name}} in one pass, so text inserted for one name is never filled again."""
    fields = {
        "issue": judge_input.issue,
        "fail_to_pass": "\n".join(judge_input.fail_to_pass),
        "gold_patch": judge_input.gold_patch,
        "agent_patch": judge_input.agent_patch,
        "trajectory": judge_input.trajectory,
    }
    return PLACEHOLDER.sub(lambda match: fields[match.group(1)], template)


def parse_verdict(text: str) -> JudgeVerdict:
    """The JSON object the text starts with. A base model keeps writing after it; that is ignored.

    Raises ValueError (a JSON or pydantic error) when the text does not start with a valid verdict.
    """
    value, _ = json.JSONDecoder().raw_decode(text.lstrip())
    return JudgeVerdict.model_validate(value)


def parse_error(text: str) -> str | None:
    try:
        parse_verdict(text)
    except ValueError as error:
        return one_line(str(error))
    return None


def one_line(text: str) -> str:
    return " ".join(text.split())


def completion_request(prompt: str, version: str) -> Request:
    return Request(
        model=JUDGE_MODEL,
        messages=({"role": "user", "content": prompt},),
        max_tokens=MAX_TOKENS,
        temperature=0.0,
        seed=SEED,
        prompt_version=version,
        chat_template=False,
    )


def repair_request(answer: str, error: str, version: str) -> Request:
    prompt = REPAIR_TEMPLATE.format(error=error, text=clip(answer.strip(), REPAIR_INPUT_CHARS))
    return completion_request(prompt, f"{version}-repair")


def judge_all(
    client: CachedClient,
    inputs: Sequence[JudgeInput],
    prompt: Prompt,
    confirm: Callable[[], bool] = ask_on_terminal,
    show: Callable[[str], None] = print,
) -> list[JudgeResult] | None:
    """Judges every input. An answer that does not parse gets one repair call, as a second batch.

    Returns None if a batch is declined.
    """
    requests = [completion_request(render(prompt.text, item), prompt.version) for item in inputs]
    answers = run_batch(client, requests, confirm, show)
    if answers is None:
        return None
    errors = {i: error for i, answer in enumerate(answers) if (error := parse_error(answer.text))}
    repair_requests = [
        repair_request(answers[i].text, error, prompt.version) for i, error in errors.items()
    ]
    repairs = run_batch(client, repair_requests, confirm, show)
    if repairs is None:
        return None
    repair_of = dict(zip(errors, repairs, strict=True))
    return [read_attempts(answer, repair_of.get(i)) for i, answer in enumerate(answers)]


def read_attempts(answer: Response, repair: Response | None) -> JudgeResult:
    """The result of the last attempt, with the tokens of every attempt added up."""
    attempts = [answer] if repair is None else [answer, repair]
    try:
        verdict = parse_verdict(attempts[-1].text)
        outcome: Outcome = "parsed" if repair is None else "repaired"
    except ValueError:
        verdict, outcome = UNREADABLE, "failed"
    return JudgeResult(
        verdict=verdict,
        outcome=outcome,
        prompt_tokens=sum(a.prompt_tokens for a in attempts),
        completion_tokens=sum(a.completion_tokens for a in attempts),
    )
