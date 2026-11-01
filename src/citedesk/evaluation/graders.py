"""Code-based graders for the golden set (evals/golden_v1.json).

Each grader compares what the app produced (`AnswerView`) with what the answer key says
(`AnswerKey`) and returns a `Grade`: 1.0 for a pass, 0.0 for a fail, or None when the check does
not apply to this case (for example, there is no section to check when the right behaviour is to
refuse). Cases where a grader does not apply are left out of that metric's average.

The graders read plain dictionaries, the shape LangSmith passes to evaluators, so they can be
tested with made-up answers and reused outside LangSmith.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from citedesk.text import split_sentences

ANSWER = "answer_with_citations"
PARTIAL = "partial_answer"
REFUSE = "refuse"

_MARKER = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class Grade:
    score: float | None  # 1.0 pass, 0.0 fail, None not applicable
    comment: str


@dataclass(frozen=True)
class AnswerView:
    """What the app produced for one question."""

    text: str
    sections: tuple[str, ...]  # section path of each citation
    refused: bool
    # The [n] numbers the citations answer to. [n] is the passage number the writer was shown,
    # so an answer may cite only [2]; the markers are not always 1, 2, 3.
    markers: tuple[int, ...] = ()


@dataclass(frozen=True)
class AnswerKey:
    """What the golden dataset says a good answer looks like."""

    expected_behavior: str
    gold_sections: tuple[str, ...]
    must_include: tuple[tuple[str, ...], ...]  # every group needs at least one alternative


def answer_view(outputs: Mapping[str, Any]) -> AnswerView:
    sections = tuple(outputs.get("sections") or ())
    markers = tuple(outputs.get("markers") or range(1, len(sections) + 1))
    return AnswerView(
        text=str(outputs.get("text", "")),
        sections=sections,
        refused=bool(outputs.get("refused", False)),
        markers=markers,
    )


def answer_key(reference: Mapping[str, Any]) -> AnswerKey:
    return AnswerKey(
        expected_behavior=str(reference["expected_behavior"]),
        gold_sections=_split(reference.get("gold_sections", ""), " | "),
        must_include=_groups(reference.get("must_include", "")),
    )


def _split(value: Any, separator: str) -> tuple[str, ...]:
    if value is None:  # an empty cell comes back from LangSmith as None, not ""
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return tuple(part.strip() for part in str(value).split(separator) if part.strip())


def _groups(value: Any) -> tuple[tuple[str, ...], ...]:
    """Read the key facts: a list of lists, or the flat text stored in LangSmith.

    The flat form joins required facts with " AND " and alternatives with "/",
    for example "20 AND not/no".
    """
    if isinstance(value, (list, tuple)):
        return tuple(tuple(str(alt) for alt in group) for group in value)
    return tuple(_split(group, "/") for group in _split(value, " AND "))


def mentions(text: str, phrase: str) -> bool:
    """Whole-word, case-insensitive match: '20' is not in '120' and 'no' is not in 'note'."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE) is not None


# --- graders ---------------------------------------------------------------------------------


def refusal_correct(view: AnswerView, key: AnswerKey) -> Grade:
    """Refused when it should refuse, and answered when it should answer."""
    if key.expected_behavior == PARTIAL:
        return Grade(1.0, "either answering the part it can or refusing is acceptable")
    if key.expected_behavior == REFUSE:
        if view.refused:
            return Grade(1.0, "refused as expected")
        return Grade(0.0, "answered a question the handbook cannot answer")
    if view.refused:
        return Grade(0.0, "refused a question the handbook can answer")
    return Grade(1.0, "answered as expected")


def section_cited(view: AnswerView, key: AnswerKey) -> Grade:
    """Every citation points into a gold section, and there is at least one."""
    if key.expected_behavior == REFUSE or view.refused:
        return Grade(None, "no answer to check")
    if not view.sections:
        return Grade(0.0, "answer has no citations")
    outside = sorted(set(view.sections) - set(key.gold_sections))
    if outside:
        return Grade(0.0, f"cited outside the gold sections: {outside}")
    return Grade(1.0, "all citations are in a gold section")


def key_facts(view: AnswerView, key: AnswerKey) -> Grade:
    """The answer states every fact the key requires."""
    if key.expected_behavior == REFUSE or not key.must_include:
        return Grade(None, "no key facts required")
    if view.refused:
        return Grade(None, "refused; see refusal_correct")
    missing = [
        "/".join(group)
        for group in key.must_include
        if not any(mentions(view.text, alternative) for alternative in group)
    ]
    if missing:
        return Grade(0.0, f"missing key facts: {missing}")
    return Grade(1.0, "all key facts present")


def every_sentence_cited(view: AnswerView, key: AnswerKey) -> Grade:
    """Each sentence carries a [n] marker, and every marker matches a real citation."""
    del key  # applies to every answer, whatever the key says
    if view.refused:
        return Grade(None, "no answer to check")
    sentences = split_sentences(view.text)
    if not sentences:
        return Grade(0.0, "answer text is empty")
    allowed = view.markers or tuple(range(1, len(view.sections) + 1))
    for sentence in sentences:
        markers = [int(number) for number in _MARKER.findall(sentence)]
        if not markers:
            return Grade(0.0, f"sentence without a citation marker: {sentence!r}")
        unknown = [m for m in markers if m not in allowed]
        if unknown:
            return Grade(0.0, f"marker {unknown} matches no citation")
    return Grade(1.0, "every sentence is cited")


GRADERS: dict[str, Callable[[AnswerView, AnswerKey], Grade]] = {
    "refusal_correct": refusal_correct,
    "section_cited": section_cited,
    "key_facts": key_facts,
    "every_sentence_cited": every_sentence_cited,
}
