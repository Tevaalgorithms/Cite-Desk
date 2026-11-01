# Week 4: evaluating CiteDesk with a golden dataset and LangSmith

This note explains what the Week 4 evaluation work is, why it was needed, how to run it again, and what it found. The numbers and the reasoning are in `evals/results/`; this page is the map.

## What this is

A repeatable way to measure how good CiteDesk's answers are, one question at a time, and to prove whether a change made things better or worse.

- **A golden dataset** (`evals/golden_v1.json`): 40 handbook questions, each with the correct behavior written down before the app is run: answer with a citation, or refuse. Mix: 20 happy path, 12 edge cases, 6 known failures, 2 adversarial (prompt injection). It is stored in LangSmith as dataset `citedesk-golden`, tag `v1`.
- **Graders** that score every answer: four code checks (`src/citedesk/evaluation/graders.py`) and one LLM judge for faithfulness (`judge.py`).
- **A runner** (`langsmith_run.py`) that asks the app all 40 questions as a LangSmith experiment, so each question leaves one trace with its scores attached, and writes a case-level CSV.
- **The written results**: failure analysis, four attempted improvements with measured deltas, and a framework document (`evals/results/`).

## Why we needed it

Before this work, CiteDesk's quality evidence was `citedesk eval-retrieval` on about 51 sample questions written by the same person who wrote the handbook. It showed that the pipeline works, but:

- the real model already passed about 97% of those questions, so there was no room to show improvement;
- there were no reference answers, so nothing measured whether an answer was *faithful* (said only what the handbook says);
- there were no per-question traces linking a score to what happened inside the app;
- nothing separated real failures from run-to-run noise, so a change that "felt better" could not be proved.

The Week 4 project asks for exactly this: define success, evaluate systematically, and report measured before/after deltas. "A successful demo does not prove reliability."

## How it works

```
golden_v1.json ──> LangSmith dataset v1 ──> runner asks CiteDesk each question
                                              │  one trace per question
                                              ▼
                      graders score the answer ──> scores stored on the trace
                                              │
                                              ▼
                              evals/results/runs/<run>.csv
```

| Grader | Type | Question it answers |
|---|---|---|
| `refusal_correct` | code | Refused when it should, answered when it should? |
| `section_cited` | code | Do all citations point into a correct handbook section? |
| `key_facts` | code | Does the answer state each required fact (whole-word match)? |
| `every_sentence_cited` | code | Does every sentence carry a `[n]` that matches a real citation? |
| `faithfulness` | LLM judge (`gpt-5.4-mini`) | Does every claim appear in the cited passage? |
| latency, tokens, cost | measured | How slow and how expensive was each question? |

A grader returns pass, fail, or "does not apply" (for example, no section to check when the right behavior is to refuse). Cases where a grader does not apply are left out of that average.

## How to run it

Needs `CITEDESK_LANGSMITH_API_KEY` and `CITEDESK_OPENAI_API_KEY` in `.env` (never committed). The run sends the synthetic Acme handbook text and the questions to LangSmith and OpenAI, and costs about $0.004 per run for the answer model (measured); the judge's cost was not measured.

```
uv run python -m citedesk.evaluation.langsmith_run --prefix my-run
```

It runs on a throwaway database containing only `data/sample/acme-handbook.md`, never your dev database. Run each setting **three times**: the same app gave `correct` between 0.90 and 0.925 and faithfulness between 0.903 and 0.968 with nothing changed, and one case is worth 2.5 to 3 points. Do not edit the dataset between a baseline and its comparison; make a new version instead.

Tests: `uv run pytest tests/unit` (the graders, judge and runner helpers are tested offline, including regression tests for two grader bugs found during the project).

## What it found (short version)

Details in `evals/results/improvements-report.md`.

- Baseline (three runs): correct 0.917, faithfulness 0.933, refusal correct 0.917, p95 latency 1.31 s, about $0.00009 per question.
- Six of 40 cases fail, from three separate causes: the relevance cutoff refusing answerable questions, the writer adding phrases the handbook does not state, and refusals after retrieval worked (the verifier rejecting a number that came from the question).
- Of four changes tried, one worked: lowering the relevance cutoff to -10.5 raised `correct` to 0.950. It is **not** the default, because the quality gate for the built-in quoting writer fails at that value (ADR-023, proposed, for review). The other three changes did not help and were reverted.
- The judge is stricter than the project owner: 60% agreement on a blind first pass over 10 answers (80% after the owner revised two labels having seen the judge).

## Limits to keep in mind

- 40 cases on a 2 KB synthetic handbook; the cutoff result rests on two questions.
- 7 cases were drafted by Claude (17.5%); all 40 were reviewed by the project owner against the handbook.
- Faithfulness is on the judge's strict standard; a human reviewer accepted some answers the judge rejected.
- LangSmith's free-tier monthly trace limit was reached during the project: the baseline and improved runs have complete traces, some later replicates have scores but incomplete traces.
- Cost figures use a recorded `gpt-5.4-nano` price that was not re-checked, and cover the answer model only, not the judge.
- This is evidence for a Week 4 report, not a release gate. RAGAS, DeepEval and the CI jobs described in `evaluation-strategy.md` are still not built.

## File map

| Path | What it is |
|---|---|
| `evals/golden_v1.json` | The 40-case dataset and its answer key |
| `evals/golden_v1_review.csv` | The same cases as a table, with the human review marks |
| `evals/golden_v1_langsmith_upload.csv` | The file used to create the LangSmith dataset |
| `src/citedesk/evaluation/graders.py`, `judge.py`, `langsmith_run.py` | Graders, judge and runner |
| `evals/results/evaluation-framework.md` | The one-line goal and the framework table |
| `evals/results/failure-analysis-baseline-v1.md` | Why the baseline failed, grouped by cause |
| `evals/results/improvements-report.md` | The four changes, measured deltas, regressions, what is next |
| `evals/results/submission-cases.csv` | Case-level spreadsheet: baseline output and score, improved output and score |
| `evals/results/runs/` | One case-level CSV per run (void runs were deleted) |
| `evals/results/judge-agreement-sheet.csv`, `judge-agreement-key.csv` | The 10-answer human check of the judge (the key holds the judge's verdicts) |
| `docs/architecture/adrs.md` (ADR-023) | The relevance-cutoff decision, proposed |
