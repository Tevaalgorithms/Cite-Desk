# Week 4 evaluation framework: CiteDesk

## The one-liner

I will measure correctness (every code check passing), faithfulness, refusal correctness, citation coverage, and latency and cost on **CiteDesk** using a golden dataset of **40 cases** (20 happy path, 12 edge, 6 known-failure, 2 adversarial) covering exact and paraphrased handbook questions, multi-part questions, unanswerable questions and prompt-injection attempts, with **code-based graders plus an LLM judge for faithfulness**. Pass bar: faithfulness at least 90%, refusal correct at least 95%, every sentence cited 100%, right section cited at least 90%, key facts at least 90%, p95 latency under 3 s, cost under $0.001 per question. I will compare **baseline against post-improvement in LangSmith**, using three runs of each because identical runs vary.

## The framework

| Field | Answer |
|---|---|
| **Agent under test** | CiteDesk, a handbook question-answering pipeline: hybrid search, a reranker, a LangGraph answer flow with a language-model writer (`gpt-5.4-nano`), and a citation verifier. It is a retrieval pipeline, not a multi-agent system (ADR-018). |
| **User outcome** | An employee gets a correct answer in which every sentence cites the handbook passage it came from, or an honest refusal when the handbook does not answer the question. |
| **Metrics** | Correct (all applicable code checks pass), faithfulness (judge), refusal correct, every sentence cited, p95 latency and cost per question. Right section cited and key facts present are also reported. |
| **Judge method** | Exact or code checks for section cited, key facts (whole-word match), refusal behavior and sentence citations; an LLM judge (`gpt-5.4-mini`, temperature 0, pinned prompt) for faithfulness; latency and cost read from the run. Human comparison with the judge: 6 of 10 agree on a blind first pass (60%), 8 of 10 after revision (80%); see "Judge agreement" below. |
| **Golden dataset** | 40 cases in `evals/golden_v1.json`, uploaded to LangSmith as `citedesk-golden` tag `v1`. 33 come from the project's existing sample questions and 7 (17.5%) were drafted by Claude; all 40 cases were reviewed by me against the handbook (the 33 existing-question cases were first checked by Claude, then verified by me). |
| **Pass bar** | Faithfulness at least 0.90; refusal correct at least 0.95; every sentence cited 1.00; right section cited at least 0.90; key facts at least 0.90; p95 latency under 3 s; cost under $0.001 per question. These numbers were proposed during the project and are not tuned to the results. |
| **Instrumentation** | One LangSmith trace per case with LangGraph, retrieve, model-call and verify child runs, and metadata for case ID, scenario type, prompt version, expected behavior, expected and predicted answer. Scores (8 per case), latency, tokens and cost are stored on the trace. |
| **Baseline run** | `baseline-v1-795b0253`: correct 0.90, faithfulness 0.931, refusal correct 0.90. Three-run mean: 0.917, 0.933, 0.917. 40 traces and 320 scores verified. (LangSmith link: see the submission form) |
| **Failure analysis** | (1) Relevance cutoff refuses answerable questions, 2 cases (`gv1-033`); (2) the writer adds unsupported phrases, 2 cases (`gv1-035`); (3) refusal after retrieval worked, 2 cases (`gv1-027`, a number from the question rejected by the verifier). Token cost is negligible, so cost is user impact: refusals are safe but unhelpful, added claims are the more serious kind. Trace run IDs are in `failure-analysis-baseline-v1.md`. |
| **Improvement hypotheses** | Four changes, one at a time: a lower relevance cutoff; a prompt rule against added commentary; a prompt rule allowing partial answers; a retry message about numbers from the question. Predictions and results are in `improvements-report.md`. |
| **Post-improvement run** | `change1-cutoff-de55c23c` (cutoff -10.5): correct 0.95, faithfulness 0.935, refusal correct 0.95. Three-run mean: correct 0.950, faithfulness 0.935, refusal correct 0.950, p95 latency 1.44 s, cost $0.000094 per question. (LangSmith link: see the submission form) |
| **What is next** | Top remaining failure: the verifier rejecting numbers that come from the question (`gv1-027`); next step is returning the verifier's exact complaint to the writer on the retry, or accepting question numbers with a test that invented numbers are still rejected. Monitoring plan is in `improvements-report.md`. |

## Result in one paragraph

Of four changes, one worked: lowering the relevance cutoff to -10.5 raised the share of cases passing every code check from 0.917 to 0.950 and fixed one answerable question that was being refused. It is not the default because the quality gate for the built-in quoting writer fails at that value, so it is documented as a recommended setting for the language-model writer (ADR-023, proposed). The other three changes did not help and were reverted, and faithfulness did not change.

## Judge agreement

On 10 answers (4 the judge marked unfaithful, 6 faithful; `judge-agreement-sheet.csv` and `judge-agreement-key.csv`), my first, blind pass marked all 10 "faithful" and agreed with the judge on 6 (60%). After I was shown the judge's verdicts I changed two rows to "not faithful" (`gv1-018`, "so expenses of 25 dollars or less do not require a receipt"; `gv1-035`, "After your parental leave"), giving 8 of 10 (80%). Because those two changes were made after seeing the judge, 80% is likely too high and 60% is the cleaner figure.

The two remaining disagreements are answers the judge marked unfaithful that I accept: `gv1-019` ("which is the maximum duration stated") and `gv1-036` (treating "multi-factor" and "two-factor" as the same). So the judge is somewhat stricter than my reading. On this sample the judge flagged both answers I finally marked unfaithful, but with only two such answers and ten in total this says little about how often it misses unfaithful answers. The faithfulness failure mode in this report ("the writer adds unsupported phrases") is defined by the judge's strict standard.

## Still pending before submission

- Loom recording and the submission form.
- The cost figures use a recorded `gpt-5.4-nano` price that was not re-checked, and cover the answer model only, not the judge.
