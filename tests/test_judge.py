import hashlib
from pathlib import Path

import pytest

from grader_proof.judge import (
    FROZEN_SHA256,
    FROZEN_VERSION,
    JUDGE_MODEL,
    PLACEHOLDERS,
    JudgeInput,
    JudgeVerdict,
    Prompt,
    judge_all,
    load_prompt,
    parse_verdict,
    patch_view,
    prompt_versions,
    render,
)
from grader_proof.llm import CachedClient, Request, Response
from grader_proof.trajectory import clip

VALID = (
    '{"evidence": "the patch never touches parse()", '
    '"failure_class": "model_failure", "confidence": 0.8}'
)
PROMPT = Prompt(version="judge-test", text="Issue: {{issue}}\nVerdict: ")


def judge_input(issue: str = "the parser drops the last line") -> JudgeInput:
    return JudgeInput(
        issue=issue,
        fail_to_pass=("tests/test_parse.py::test_last_line",),
        gold_patch="+gold",
        agent_patch="+agent",
        trajectory="## Commands run\npytest",
    )


class FakeTransport:
    """Answers the judge prompt with `first` and the repair prompt with `repair`."""

    def __init__(self, first: str, repair: str = VALID) -> None:
        self.answers: dict[str, str] = {"judge-test": first, "judge-test-repair": repair}
        self.calls: list[Request] = []

    def complete(self, request: Request) -> Response:
        self.calls.append(request)
        return Response(
            text=self.answers[request.prompt_version], prompt_tokens=100, completion_tokens=20
        )


def run(transport: FakeTransport, tmp_path: Path, inputs: list[JudgeInput] | None = None) -> list:
    results = judge_all(
        CachedClient(transport, tmp_path),
        inputs or [judge_input()],
        PROMPT,
        confirm=lambda: True,
        show=lambda _: None,
    )
    assert results is not None
    return results


def test_parse_reads_the_first_json_object_and_ignores_what_the_model_wrote_after() -> None:
    verdict = parse_verdict("  " + VALID + "\n\n## Case 4\nIssue: something else")
    assert verdict == JudgeVerdict(
        evidence="the patch never touches parse()", failure_class="model_failure", confidence=0.8
    )


@pytest.mark.parametrize(
    "text",
    [
        "The agent failed because",
        '{"evidence": "x", "failure_class": "model_failure"',
        '{"evidence": "x", "failure_class": "bad_luck", "confidence": 0.5}',
        '{"evidence": "x", "failure_class": "model_failure", "confidence": 1.5}',
        '{"evidence": "x", "failure_class": "model_failure"}',
        '["model_failure"]',
    ],
)
def test_parse_rejects_text_that_is_not_a_valid_verdict(text: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 (JSON and pydantic errors are both ValueErrors)
        parse_verdict(text)


def test_render_fills_every_placeholder() -> None:
    text = "{{issue}}|{{fail_to_pass}}|{{gold_patch}}|{{agent_patch}}|{{trajectory}}"
    assert render(text, judge_input("bug")) == (
        "bug|tests/test_parse.py::test_last_line|+gold|+agent|## Commands run\npytest"
    )


def test_render_does_not_substitute_inside_inserted_text() -> None:
    assert render("{{issue}}", judge_input("see {{trajectory}}")) == "see {{trajectory}}"


def test_render_rejects_an_unknown_placeholder() -> None:
    with pytest.raises(KeyError, match="notes"):
        render("{{notes}}", judge_input())


def test_a_valid_answer_is_parsed_with_one_call(tmp_path: Path) -> None:
    transport = FakeTransport(first=VALID)
    [result] = run(transport, tmp_path)
    assert result.outcome == "parsed"
    assert result.verdict.failure_class == "model_failure"
    assert len(transport.calls) == 1


def test_the_judge_request_is_a_plain_text_completion_for_the_judge_model(tmp_path: Path) -> None:
    transport = FakeTransport(first=VALID)
    run(transport, tmp_path)
    [request] = transport.calls
    assert request.model == JUDGE_MODEL
    assert request.chat_template is False
    assert request.temperature == 0
    assert request.prompt_version == "judge-test"
    assert request.messages[0]["content"] == "Issue: the parser drops the last line\nVerdict: "


def test_invalid_json_gets_one_repair_retry(tmp_path: Path) -> None:
    transport = FakeTransport(first="The agent failed because it", repair=VALID)
    [result] = run(transport, tmp_path)
    assert result.outcome == "repaired"
    assert result.verdict.failure_class == "model_failure"
    assert len(transport.calls) == 2
    assert "The agent failed because it" in transport.calls[1].messages[0]["content"]


def test_a_failed_repair_is_recorded_as_unclear(tmp_path: Path) -> None:
    transport = FakeTransport(first="not json", repair="still not json")
    [result] = run(transport, tmp_path)
    assert result.outcome == "failed"
    assert result.verdict.failure_class == "unclear"
    assert len(transport.calls) == 2


def test_only_invalid_answers_are_repaired(tmp_path: Path) -> None:
    class Mixed(FakeTransport):
        def complete(self, request: Request) -> Response:
            if (
                "broken" in request.messages[0]["content"]
                and request.prompt_version == "judge-test"
            ):
                self.calls.append(request)
                return Response(text="oops", prompt_tokens=100, completion_tokens=5)
            return super().complete(request)

    transport = Mixed(first=VALID)
    results = run(transport, tmp_path, [judge_input("fine"), judge_input("broken")])
    assert [r.outcome for r in results] == ["parsed", "repaired"]
    assert len(transport.calls) == 3


def test_tokens_add_up_across_the_first_answer_and_the_repair(tmp_path: Path) -> None:
    [result] = run(FakeTransport(first="oops"), tmp_path)
    assert (result.prompt_tokens, result.completion_tokens) == (200, 40)


def test_declining_the_batch_makes_no_call(tmp_path: Path) -> None:
    transport = FakeTransport(first=VALID)
    client = CachedClient(transport, tmp_path)
    results = judge_all(client, [judge_input()], PROMPT, confirm=lambda: False, show=lambda _: None)
    assert results is None
    assert transport.calls == []


@pytest.mark.parametrize("version", prompt_versions())
def test_every_prompt_version_uses_only_known_placeholders(version: str) -> None:
    prompt = load_prompt(version)
    rendered = render(prompt.text, judge_input())
    assert "{{" not in rendered
    assert all("{{" + name + "}}" in prompt.text for name in PLACEHOLDERS)


def test_the_frozen_prompt_has_not_changed() -> None:
    text = load_prompt(FROZEN_VERSION).text
    assert hashlib.sha256(text.encode()).hexdigest() == FROZEN_SHA256


def diff(path: str, body: str = "+x") -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}\n"


def test_patch_view_shows_gold_files_first_and_hidden_or_cache_files_last() -> None:
    patch = diff(".hypothesis/x") + diff("reproduce.py") + diff("pkg/core.py") + diff("pkg/a.pyc")
    view = patch_view(patch, 10_000, first={"pkg/core.py"})
    order = [line.split(" b/")[1] for line in view.splitlines() if line.startswith("diff --git")]
    assert order == ["pkg/core.py", "reproduce.py", ".hypothesis/x", "pkg/a.pyc"]


def test_patch_view_cuts_the_first_file_that_does_not_fit_and_lists_the_rest() -> None:
    patch = diff("a.py", "+" + "a" * 50) + diff("b.py", "+" + "b" * 500) + diff("c.py")
    view = patch_view(patch, 200)
    assert "diff --git a/a.py" in view
    assert "diff --git a/b.py" in view
    assert "b" * 500 not in view
    assert "diff --git a/c.py" not in view
    assert view.endswith("... 1 more file not shown: c.py")


def test_patch_view_cuts_text_without_diff_headers() -> None:
    assert patch_view("just text " * 100, 50) == clip("just text " * 100, 50)


def test_patch_view_of_an_empty_patch_is_empty() -> None:
    assert patch_view("", 100) == ""
