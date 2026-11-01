import json
from pathlib import Path

import pytest

from citedesk.evaluation.graders import (
    AnswerKey,
    AnswerView,
    answer_key,
    answer_view,
    every_sentence_cited,
    key_facts,
    mentions,
    refusal_correct,
    section_cited,
)

VACATION = "Time off > Vacation"
GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden_v1.json"


def view(
    text: str = "Full-time employees receive 20 days [1].",
    sections: tuple[str, ...] = (VACATION,),
    refused: bool = False,
) -> AnswerView:
    return AnswerView(text=text, sections=sections, refused=refused)


def key(
    behavior: str = "answer_with_citations", facts: tuple[tuple[str, ...], ...] = (("20",),)
) -> AnswerKey:
    return AnswerKey(behavior, (VACATION,), facts)


REFUSED = view(text="", sections=(), refused=True)


def test_whole_word_matching() -> None:
    assert mentions("You get 20 days.", "20")
    assert not mentions("You get 120 days.", "20")
    assert not mentions("Bring a doctor's note.", "no")
    assert mentions("No, alcohol is not reimbursed.", "no")
    assert mentions("Report it within 24 HOURS.", "24 hours")
    assert mentions("Core hours are 10:00 to 15:00.", "10:00")


def test_key_facts_pass_and_fail() -> None:
    assert key_facts(view(), key()).score == 1.0
    wrong = key_facts(view(text="Employees get 25 days [1]."), key())
    assert wrong.score == 0.0
    assert "20" in wrong.comment
    two = key(facts=(("20",), ("10",)))
    assert key_facts(view(), two).score == 0.0  # the second fact is missing
    assert key_facts(view(text="20 vacation and 10 sick days [1]."), two).score == 1.0


def test_key_facts_not_applicable() -> None:
    assert key_facts(view(), key(facts=())).score is None
    assert key_facts(REFUSED, key()).score is None
    assert key_facts(view(), key("refuse")).score is None


def test_refusal_correct() -> None:
    assert refusal_correct(REFUSED, key("refuse")).score == 1.0
    assert refusal_correct(view(), key("refuse")).score == 0.0  # answered the unanswerable
    assert refusal_correct(view(), key()).score == 1.0
    assert refusal_correct(REFUSED, key()).score == 0.0  # refused the answerable
    assert refusal_correct(REFUSED, key("partial_answer")).score == 1.0
    assert refusal_correct(view(), key("partial_answer")).score == 1.0


def test_section_cited() -> None:
    assert section_cited(view(), key()).score == 1.0
    wrong = section_cited(view(sections=("Expenses > Meals",)), key())
    assert wrong.score == 0.0
    assert "Expenses > Meals" in wrong.comment
    assert section_cited(view(sections=()), key()).score == 0.0
    assert section_cited(view(), key("refuse")).score is None
    assert section_cited(REFUSED, key()).score is None


def test_every_sentence_cited() -> None:
    assert every_sentence_cited(view(), key()).score == 1.0
    assert (
        every_sentence_cited(view(text="You get 20 days. It is generous [1]."), key()).score == 0.0
    )
    assert (
        every_sentence_cited(view(text="You get 20 days [2]."), key()).score == 0.0
    )  # no citation 2
    assert every_sentence_cited(view(text=""), key()).score == 0.0
    assert every_sentence_cited(REFUSED, key()).score is None


def test_answer_key_reads_the_langsmith_flat_format() -> None:
    parsed = answer_key(
        {
            "expected_behavior": "answer_with_citations",
            "gold_sections": "Time off > Vacation | About this handbook",
            "must_include": "20 AND not/no",
        }
    )
    assert parsed.gold_sections == ("Time off > Vacation", "About this handbook")
    assert parsed.must_include == (("20",), ("not", "no"))
    empty = answer_key({"expected_behavior": "refuse", "gold_sections": "", "must_include": ""})
    assert empty.gold_sections == ()
    assert empty.must_include == ()


def test_every_reference_answer_passes_its_own_key_facts() -> None:
    """The answer key must agree with itself: a reference answer states its own required facts."""
    cases = json.loads(GOLDEN.read_text())
    assert len(cases) == 40
    for case in cases:
        flat = {
            "expected_behavior": case["expected_behavior"],
            "gold_sections": " | ".join(case["gold_sections"]),
            "must_include": " AND ".join("/".join(group) for group in case["must_include"]),
        }
        parsed = answer_key(flat)
        assert parsed.must_include == tuple(tuple(g) for g in case["must_include"]), case["id"]
        reference = AnswerView(case["reference_answer"], tuple(case["gold_sections"]), False)
        grade = key_facts(reference, parsed)
        assert grade.score in (1.0, None), f"{case['id']}: {grade.comment}"


@pytest.mark.parametrize("behavior", ["refuse", "answer_with_citations", "partial_answer"])
def test_unknown_inputs_do_not_crash(behavior: str) -> None:
    for grader in (refusal_correct, section_cited, key_facts, every_sentence_cited):
        grader(REFUSED, key(behavior))
        grader(view(), key(behavior))


def test_an_answer_may_cite_only_passage_two() -> None:
    """[n] is the passage number the writer saw, not the position in the citation list."""
    outputs = {
        "text": "Access ends at the close of your last day [2].",
        "sections": ["A > B"],
        "markers": [2],
    }
    assert every_sentence_cited(answer_view(outputs), key()).score == 1.0
    stray = {**outputs, "text": "Access ends at the close of your last day [3]."}
    assert every_sentence_cited(answer_view(stray), key()).score == 0.0


def test_an_empty_cell_from_langsmith_means_nothing_required() -> None:
    parsed = answer_key(
        {"expected_behavior": "answer_with_citations", "gold_sections": None, "must_include": None}
    )
    assert parsed.gold_sections == ()
    assert parsed.must_include == ()
    assert key_facts(view(), parsed).score is None
