from types import SimpleNamespace
from typing import Any

import openai
import pytest

from citedesk.evaluation.judge import (
    JUDGE_PROMPT_VERSION,
    FaithfulnessJudge,
    JudgeError,
)


class FakeClient:
    """Stands in for the OpenAI client and records what the judge sent."""

    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        message = SimpleNamespace(content=self.reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def run(reply: str | Exception) -> tuple[FakeClient, Any]:
    client = FakeClient(reply)
    verdict = FaithfulnessJudge(client).judge(
        "How many days?", "20 days [1].", {1: "20 days of vacation."}
    )
    return client, verdict


def test_faithful_and_unfaithful_verdicts() -> None:
    _, good = run('{"reasoning": "Matches passage 1.", "faithful": true}')
    assert good.score == 1.0
    assert good.reasoning == "Matches passage 1."
    _, bad = run('{"reasoning": "Adds a bonus day.", "faithful": false}')
    assert bad.score == 0.0


def test_request_is_pinned_and_numbers_the_passages() -> None:
    client, _ = run('{"reasoning": "ok", "faithful": true}')
    call = client.calls[0]
    assert call["model"] == "gpt-5.4-mini"
    assert call["temperature"] == 0
    assert "[1] 20 days of vacation." in call["messages"][1]["content"]
    assert len(JUDGE_PROMPT_VERSION) == 8


@pytest.mark.parametrize(
    "reply",
    ["not json", "{}", '{"faithful": "yes", "reasoning": "x"}', '{"reasoning": "x"}', "[]"],
)
def test_unusable_output_raises(reply: str) -> None:
    with pytest.raises(JudgeError):
        run(reply)


def test_model_errors_become_judge_errors() -> None:
    error = openai.APIConnectionError(request=SimpleNamespace())  # type: ignore[arg-type]
    with pytest.raises(JudgeError):
        run(error)


def test_passages_are_labelled_with_their_real_marker_numbers() -> None:
    client = FakeClient('{"reasoning": "ok", "faithful": true}')
    FaithfulnessJudge(client).judge("Q?", "A [3].", {3: "third passage", 1: "first passage"})
    content = client.calls[0]["messages"][1]["content"]
    assert "[1] first passage\n[3] third passage" in content
