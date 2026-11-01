from citedesk.evaluation.langsmith_run import code_evaluator, correct, percentile, summarize

REFERENCE = {
    "expected_behavior": "answer_with_citations",
    "gold_sections": "Time off > Vacation",
    "must_include": "20",
}
GOOD = {"text": "You get 20 days [1].", "sections": ["Time off > Vacation"], "refused": False}


def test_percentile() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert percentile(values, 0.5) == 5.0
    assert percentile(values, 0.95) == 10.0
    assert percentile([2.5], 0.95) == 2.5


def test_correct_passes_a_good_answer_and_names_the_failed_check() -> None:
    assert correct(GOOD, REFERENCE)["score"] == 1.0
    wrong = correct({**GOOD, "text": "You get 25 days [1]."}, REFERENCE)
    assert wrong["score"] == 0.0
    assert "key_facts" in wrong["comment"]


def test_code_evaluator_returns_the_langsmith_shape() -> None:
    result = code_evaluator("key_facts")(GOOD, REFERENCE)
    assert result == {"key": "key_facts", "score": 1.0, "comment": "all key facts present"}


def test_summarize_skips_not_applicable_scores() -> None:
    rows = [
        {"scenario_type": "happy", "scores": {"key_facts": 1.0, "section_cited": None}},
        {"scenario_type": "edge", "scores": {"key_facts": 0.0, "section_cited": 1.0}},
    ]
    summary = summarize(rows)
    assert summary["key_facts"] == {"all": 0.5, "happy": 1.0, "edge": 0.0}
    assert summary["section_cited"] == {"all": 1.0, "edge": 1.0}
