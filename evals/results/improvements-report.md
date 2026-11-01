# Improvements and measured deltas

Dataset: LangSmith `citedesk-golden`, tag `v1`, 40 cases (20 happy, 12 edge, 6 known failure, 2 adversarial). Writer `gpt-5.4-nano`, judge `gpt-5.4-mini`, local embedding and reranker models. All runs use the same dataset version, the same graders and one case at a time. Case-level results are in `evals/results/runs/<run>.csv`.

## How to read the numbers

The same app run three times gave `correct` of 0.90, 0.925 and 0.925, and faithfulness between 0.903 and 0.968 on identical prompts. One case is 2.5 to 3 points. So every comparison below uses three runs per setting, and a one-case difference is treated as noise.

An early run (`baseline-4776a6de`) was scored by graders with two bugs (since fixed, with tests) and is void. Two runs of change 4 (`change4-retry`, `change4-retry-r2`) used a prompt I had accidentally malformed while reverting an earlier edit; they are void and were re-run as `change4-retry-v2`.

## Baseline versus final (three runs each)

Final = the app unchanged except `CITEDESK_MIN_RELEVANCE=-10.5` (change 1).

| Metric | Pass bar | Baseline mean (runs) | Final mean (runs) | Delta |
|---|---|---|---|---|
| Correct (all applicable code checks) | not set | 0.917 (0.90, 0.925, 0.925) | 0.950 (0.95, 0.95, 0.95) | **+0.033** |
| Refusal correct | at least 0.95 | 0.917 | 0.950 | **+0.033** (now at the bar) |
| Faithfulness (judge) | at least 0.90 | 0.933 | 0.935 (0.935, 0.903, 0.968) | +0.002, noise |
| Every sentence cited | 1.00 | 1.000 | 1.000 | 0 |
| Right section cited | at least 0.90 | 1.000 | 1.000 | 0 |
| Key facts present | at least 0.90 | 1.000 | 1.000 | 0 |
| p95 latency | under 3 s | 1.31 s (1.22 to 1.44) | 1.44 s | +0.13 s, inside baseline spread |
| Cost per question | under $0.001 | $0.000088 | $0.000094 | +7%, from answering two more questions |

Cost uses the `gpt-5.4-nano` price recorded in `docs/evaluation/evaluation-strategy.md`, which was not re-checked, and covers the answer model only, not the judge.

Traces: baseline `baseline-v1-795b0253` and improved `change1-cutoff-de55c23c` both have all 40 traces and 320 scores in LangSmith. The two later replicates (`final-cutoff-only-r2`, `-r3`) were run after the free-tier monthly trace limit was hit, so their scores are in the CSVs but their traces are incomplete or missing.

## The four changes

| # | Lever | Change | Targeted failure | Predicted | Measured | Kept? |
|---|---|---|---|---|---|---|
| 1 | Retrieval tuning | Relevance cutoff -10.0 to -10.5 (`CITEDESK_MIN_RELEVANCE`) | Mode 1: refused below the cutoff (`gv1-033`, `gv1-034`) | Refusal correct up from 0.90 and no new wrong answers | `gv1-033` fixed in 3 of 3 runs; `correct` 0.917 to 0.950. `gv1-034` **not** fixed: its right section ranks second at -10.51, one hundredth under the new cutoff. No unanswerable question was answered with the real writer. | **As a recommended setting only.** The default stays -10.0 because the built-in quoting writer's gate fails at -10.5 (see below). |
| 2 | Prompt | New rule 7: say only what the passages say, no commentary | Mode 2: added phrases (`gv1-019`, `gv1-035`) | Faithfulness up from 0.93 | Faithfulness 0.925 (0.903, 0.903, 0.968) versus 0.935 for the cutoff alone: no gain. `gv1-019` improved (1 of 3 runs failing to 0), `gv1-018` broke (0 of 3 to 2 of 3), `gv1-035` unchanged (2 of 3). Cost per question +11% over the cutoff alone. | No. Reverted. |
| 3 | Prompt | Allow answering with a stated limit (for example "administrators only") | Mode 3: `NO_ANSWER` on a partly answerable question (`gv1-036`) | Fewer wrong refusals; risk of answering unanswerable questions | `gv1-036` answered but still failed (judge: adds "multi-factor means two-factor"). Faithfulness 0.903 and 0.935 in two runs, versus 0.925 mean for change 2. No unanswerable question was answered. | No. Reverted. |
| 4 | Prompt (retry) | Retry message: do not repeat numbers from the question | Mode 3: verifier rejects "4 days" taken from the question (`gv1-027`) | `gv1-027` answered | Not fixed: the model wrote "4 consecutive sick days" again on both retries, in both valid runs, and still refused after two model calls. | No. Reverted. |

**Why the cutoff is not the default.** With -10.5, `citedesk eval-retrieval --models local --check evals/baselines.json` fails on `golden`: `confidently_wrong` rose from 0 to 2 and `unanswerable_answered` from 0 to 1. The gate uses the built-in quoting writer, which cannot refuse, so "What is the guest wifi password?" (score -10.01) is answered. The gate was not changed, per `AGENTS.md`. Recorded as ADR-023 (proposed, for review). The language model refused all 14 unanswerable sample questions at both values.

## Regressions and negative results

- Change 2 broke `gv1-018` ("Do I have to keep receipts for small purchases?"): the answer began adding inferences ("so expenses of 25 dollars or less do not require a receipt").
- Change 3 lowered faithfulness in the first run (0.903) and gave no net gain.
- Changes 2 to 4 were all reverted; the only difference between the code now and the original is the `prompt_version` fingerprint added for tracing.
- A single run of change 2 looked like a clear win (faithfulness 0.968). Repeats of the same prompt gave 0.935 and 0.903, so that figure was luck.

## Remaining failures (final configuration, three runs)

| Case | Failing runs | Cause |
|---|---|---|
| `gv1-027` (4 days sick, note needed?) | 3 of 3 | Verifier rejects the number 4, which comes from the question |
| `gv1-034` (when online?) | 3 of 3 | Retrieval ranks Core hours second, at -10.51, just under the cutoff |
| `gv1-036` (two-factor mandatory?) | 3 of 3 | Writer returns `NO_ANSWER`, or the judge rejects its answer |
| `gv1-035` (parental leave then remote?) | 2 of 3 | Writer adds "After your parental leave" |
| `gv1-019` | 1 of 3 | Writer adds "which is the maximum duration stated" (flaky) |

## Caveat on faithfulness

Faithfulness is scored by an LLM judge that is somewhat stricter than the project owner. On 10 answers they agreed on 6 in a blind first pass (60%) and on 8 after the owner revised two labels having seen the judge's verdicts (80%, likely too high). The two remaining disagreements are the judge flagging "which is the maximum duration stated" (`gv1-019`) and a multi-factor versus two-factor equivalence (`gv1-036`) that the owner accepted. The unsupported-addition failure mode and the faithfulness numbers above are on the judge's strict standard. See `evaluation-framework.md`.

## What is next

1. **Top remaining failure: refusals the verifier causes (`gv1-027`).** Proposed: pass the verifier's exact complaint back to the writer on the retry, or accept numbers that appear in the user's question while still rejecting invented ones. The second weakens a safety check, so it needs an ADR and a test that invented numbers are still rejected.
2. **Retrieval ranking (`gv1-034`).** Try query expansion or a larger rerank pool, and judge it on questions outside this dataset.
3. **Judge calibration.** Done on 10 answers: 60% blind agreement (80% after revision), the judge somewhat stricter than a human reviewer. Next: agree on one written definition of "faithful" (are small inferences allowed?), re-label, and measure on more than 10 answers, including some a human marks unfaithful.
4. **More data.** 40 cases on a 2 KB synthetic handbook, with 33 labels checked by Claude against the handbook and 7 by you. Expand and review before relying on any threshold.

Production monitoring plan (LangSmith, keeping prompt version, run name, environment and case ID in metadata): alert if faithfulness or task completion drops by more than 5 points over a 7-day rolling window; if p95 cost per run exceeds budget by 25% over 24 hours; if p95 latency exceeds the SLA on more than 5% of runs; if the refusal rate changes by more than 2 times its baseline; and if any single tool or model call fails more than 5% of the time in an hour. The "5 points" is my starting guess, not a measured value.
