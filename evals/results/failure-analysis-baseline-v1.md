# Failure analysis: baseline-v1

Experiment `baseline-v1-795b0253` (LangSmith, dataset `citedesk-golden` tag `v1`, 40 cases, prompt version `d4827b68`, writer `gpt-5.4-nano`, judge `gpt-5.4-mini`). Case-level results: `evals/results/runs/baseline-v1.csv`. An earlier run (`baseline-4776a6de`) is invalid: it was scored by graders with two bugs (since fixed, with regression tests).

## Summary

6 of 40 cases fail. 33 cases should be answered and 29 were answered, so 4 answerable questions were refused. Two answered cases contain claims the handbook does not make.

| # | Failure mode | Cases | Stage | Share |
|---|---|---|---|---|
| 1 | Search results scored just under the relevance cutoff, so the question was refused before the writer saw it | gv1-033, gv1-034 | Retrieval | 2 of 33 answerable (6%) |
| 2 | The writer added a phrase the handbook does not state | gv1-019, gv1-035 | Generation | 2 of 29 answered (7%) |
| 3 | Refused after retrieval succeeded: verifier rejected a number taken from the question (gv1-027); writer said NO_ANSWER for a partly answerable question (gv1-036) | gv1-027, gv1-036 | Verifier / writer | 2 of 33 answerable (6%) |

Counts are small (1 case = 2.5 to 3 points), and gv1-036 passed in an earlier run, so single-run differences of one case are noise.

## Evidence per mode

**1. Relevance cutoff (retrieval).** Refusal reason `nothing_relevant_found`. The top reranker score was -10.29 (gv1-033, right section found) and -10.35 (gv1-034, wrong top section: Parental leave instead of Core hours). The cutoff is -10.0 (`LOCAL_MIN_RELEVANCE`), whose own comment says it costs the hardest paraphrases. Unanswerable cases refused at the cutoff scored -11.21 or lower, so the data show a gap between -10.35 and -11.21. Caution: that gap comes from 40 cases that include the ones that exposed it.
- Example trace gv1-033: run `01a19757-f31b-74f0-b6a7-eba1a88a405d`; gv1-034: run `01a19757-be9d-78d1-8fba-bcdad725c3d3`.

**2. Unsupported additions (generation).** The judge flagged gv1-019 ("...which is the maximum duration stated") and gv1-035 ("After your parental leave, you may..."). The numbers were right, so the code graders and the verifier (numbers, names, word overlap) did not catch them; only the faithfulness judge did.
- gv1-019: run `01a19757-bed5-7bf2-aeff-de7e4d6c1326`; gv1-035: run `01a19757-fb38-7e10-aae6-ca9e046b2e18`.

**3. Refused after retrieval succeeded.**
- gv1-027, reason `could_not_verify_answer`: the model answered correctly ("a doctor's note is required after 3 consecutive sick days, and 4 consecutive sick days meets that condition [1]"), but the verifier said "Number 4 does not appear in the cited passage". The 4 came from the question. Two model calls were spent and the answer was refused. Run `01a19757-edc5-7011-b9ba-e3c59628b48e`.
- gv1-036, reason `passages_do_not_answer`: the model returned NO_ANSWER; the passage says multi-factor authentication is required for administrator accounts. Prompt rule 5 ("related text that does not answer the question is not an answer") likely pushes it to refuse instead of stating the limit. Run `01a19757-f907-79e0-89a0-04dd53f0efd5`.

## Cost of each mode

Token cost is negligible (about $0.00009 per question, nano price from the repo docs, unverified), so cost here means effect on users, not dollars. I have not measured any dollar or time cost of a refused question; set an assumption before quoting one.
- Modes 1 and 3: the employee gets no answer and has to ask a person. Safe, but unhelpful. Mode 3 also wasted a second model call on gv1-027.
- Mode 2: an answer that states something the handbook does not. Rare, but the more serious kind, because it looks authoritative.

## Not failures

- gv1-032 was refused (`could_not_verify_answer`); its key allows refusing a mixed answerable and unanswerable question.
- Suspected known failures gv1-037 and gv1-038 passed. gv1-035 was relabeled after its key was found flawed. Of the 6 known-failure cases, 4 failed in this run (033, 034, 035, 036), one of which (036) also passed in the first run.
