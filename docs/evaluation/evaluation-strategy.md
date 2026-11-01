# CiteDesk — Evaluation Strategy

Every pull request is scored on retrieval, answer quality and citations, and the build fails when a gate is missed. Deterministic checks catch most regressions for free; RAGAS and DeepEval add judged metrics on a small, cached set.

## What is implemented today

`citedesk eval-retrieval` (see the README) measures, without any API key (it always uses a throwaway database, an in-memory index and the built-in writer unless you pass `--writer openai`, whatever your `.env` says):

- **Retrieval by stage:** keyword only, vector only, both fused, and fused + reranked. Reported as Recall@1, @3, @5 and MRR, split by question type (exact wording versus paraphrase).
- **Answers:** whether the right section was cited, refusals of unanswerable questions, and "confidently wrong" answers (cited the wrong section, or answered an unanswerable question).
- **Threshold calibration:** the top reranker score of every question, so the relevance threshold comes from data.
- **Gates:** `--check evals/baselines.json` exits 1 if recall, MRR or correct answers fall below the recorded floor, or if confidently-wrong answers rise above the recorded ceiling. The offline backend is gated in the normal test suite; the local backend is gated by `tests/models` and by a separate CI job.

Not implemented yet: RAGAS and DeepEval (they need an LLM judge and an API key), the 120-question golden set reviewed by a person, and the nightly ablation run. The sample sets are small (27, 12 and 12 questions), written by the same author as the handbook, and the handbook is synthetic, so they show that the pipeline works and which stage helps, not how it will perform on a real handbook.

## Week 4: golden dataset, graders and LangSmith experiments

A second, smaller evaluation was added for the Week 4 project: a 40-case reviewed golden dataset, code graders plus an LLM faithfulness judge, and LangSmith experiments with one trace per question. It measures things the retrieval harness above does not (faithfulness, refusal behavior, per-question latency and cost) and was used to try four improvements. What it is, why it exists, how to run it and what it found: [week4-evaluation.md](week4-evaluation.md). It is not a release gate and does not replace the RAGAS and DeepEval work described below.

## Measured results on the sample handbook

Real local models versus the offline stand-ins, final pipeline (fused + reranked), answerable questions:

| Question set | What it is | Backend | Right section first | In top 3 | Answered correctly | Cited wrong section or answered an unanswerable question |
| --- | --- | --- | --- | --- | --- | --- |
| `golden` (21 answerable, 6 not) | Used to calibrate the threshold, so optimistic | offline | 0.81 | 0.90 | 13 of 21 | 1 |
| | | local | 0.95 | 1.00 | 19 of 21 | 0 |
| `heldout` (8 answerable, 4 not) | Used for diagnosis, now a validation set | offline | 0.63 | 0.63 | 3 of 8 | 1 |
| | | local | 0.88 | 1.00 | 6 of 8 | 2 |
| `test` (8 answerable, 4 not) | Unseen, run once | offline | 0.88 | 0.88 | 2 of 8 | 0 |
| | | local | 1.00 | 1.00 | 8 of 8 | 1 |

Reading it: the real models clearly beat the stand-ins on finding the right section and on answering paraphrased questions. Both still sometimes answer an unanswerable question that is close to a covered topic (2 of 14 unanswerable questions across the local runs). Before reranking, plain vector search beat the fused keyword-plus-vector ranking on paraphrases (Recall@1 0.90 versus 0.81 on `golden`), and the reranker repaired that, which is why hybrid retrieval is only worth it with a reranker here.

## Choosing the answer model (measured 2026-10-17)

The same 51 sample questions (all three sets) were answered with the real model, using the local embedding model and cross-encoder for retrieval. `citedesk eval-retrieval --models local --writer openai --openai-model <name>` repeats this.

| | Quoting writer (no model) | `gpt-5.4-nano` | `gpt-5.4-mini` |
| --- | --- | --- | --- |
| Answerable questions answered correctly | 34 of 37 | 34 of 37 | 35 of 37 |
| Cited a wrong section | 1 | 0 | 0 |
| Unanswerable questions answered anyway | 3 of 14 | 0 of 14 | 0 of 14 |
| Answer time per question | instant | about 0.9 s | about 0.9 s |
| Tokens per question | none | about 300 in, 18 out | about 300 in, 18 out |
| Approximate cost per question | none | about $0.00008 | about $0.0003 |

- **What the model adds.** On questions the handbook can answer, all three are close (34, 34 and 35 of 37). The difference is on questions it cannot answer: the quoting writer answered 3 of 14 of them from a nearby passage (for example the cafeteria price), while both models refused all 14, because they can say the passages do not answer the question. They can also combine facts ("16 weeks, which can start up to 2 weeks before the birth"), which the quoting writer cannot.
- **Nano versus mini.** They differ on 1 of 37 answerable questions, and the difference was a safe refusal ("Are two-factor logins mandatory?", where the handbook says only administrators must use it). The MVP default is therefore the cheaper `gpt-5.4-nano`. Switch with `CITEDESK_OPENAI_MODEL=gpt-5.4-mini`; no code change.
- **Prices.** `gpt-5.4-nano`: $0.20 per million input tokens and $1.25 per million output, from [OpenAI's model page](https://developers.openai.com/docs/models/gpt-5.4-nano). `gpt-5.4-mini`: $0.75 and $4.50, from a third-party tracker only ([source](https://pricepertoken.com/pricing-page/model/openai-gpt-5.4-mini)), unconfirmed. The per-question costs above are my arithmetic from these prices and the measured tokens. Re-check prices before budgeting.
- **Limits of this evidence.** 37 answerable and 14 unanswerable synthetic questions, written by the same author as the handbook, on short passages (about 300 prompt tokens per call). A real handbook has longer sections, so expect more tokens per question (up to roughly 6 passages of about 300 tokens each). Real-model scores on `golden` benefit from a threshold calibrated on that set. A single run per model; results at temperature 0 can still vary a little.

## Multi-part questions and the agent decision

`evals/sample/multistep.json` holds 12 questions that each need two or three sections. They are scored two ways, both reported by `citedesk eval-retrieval`:

- **Coverage** (deterministic, gated): did retrieval hand the writer every needed section? **12 of 12.** This is the measure that decides whether an agent could help, because an agent only improves retrieval.
- **Answer completeness** (depends on the writer): did the answer cite every needed section? `gpt-5.4-nano` 11 of 12, `gpt-5.4-mini` 10 of 12, built-in quoting writer 0 of 12. One of nano's misses is a flawed test question, not a failure.

Conclusion (ADR-018): no agent is built; what handles multi-part questions is the language model combining the passages retrieval already supplies. If coverage ever drops below complete on a larger corpus, that is the evidence to build one.

## Setting up judged evaluation: what you need to provide

RAGAS and DeepEval score answers with a language model acting as judge. Nothing runs until these are decided:

| Item | Why | Status |
| --- | --- | --- |
| A judge-model API key | The judge is a paid model call. The OpenAI key you already have is enough for both tools | Key exists in `.env` and SSM |
| The key as a GitHub Actions secret (for example `OPENAI_API_KEY`) | CI cannot read your `.env` or SSM. Pull requests from forks never receive secrets, so they run only the free checks | Not added |
| One pinned judge model | Pinning keeps scores comparable between runs. A cheaper model is fine for pull requests, a stronger one for the nightly run | Not chosen |
| A monthly budget (suggested: $100) | Judged runs cost money. Two limits apply: a per-run cap on judge calls (`CITEDESK_EVAL_MAX_JUDGE_CALLS_PER_RUN`, 300 by default) and a monthly spending limit set in the OpenAI dashboard, which only you can set | Not set |
| Which changes trigger a judged run | To avoid paying on every pull request: only changes to retrieval, prompts, the writer, the verifier or the evaluation code | Proposed in this document |
| A person who reviews the golden questions | Judged scores are only as good as the questions and reference answers | Not assigned |

The cost figures in this document are estimates from third-party price pages and must be rechecked against your actual model before you set the budget.

## Metrics and starting gates

These thresholds are **starting guesses**. They are calibrated on the first measured baseline and then ratcheted up, never loosened to make a failing run pass.

| Layer | Metric | Tool | Starting gate |
| --- | --- | --- | --- |
| Retrieval | Recall@5, MRR@10 against gold passages | Deterministic code | Recall@5 at least 0.85 |
| Retrieval | Context precision | RAGAS | At least 0.75 |
| Retrieval | Context recall | RAGAS | At least 0.80 |
| Generation | Faithfulness | RAGAS and DeepEval | At least 0.90 |
| Generation | Answer relevancy | RAGAS | At least 0.85 |
| Citations | Every sentence cited; quotes verbatim; numbers and names traceable | Deterministic verifier | 100% |
| Robustness | Planted prompt-injection documents change nothing | Deterministic tests plus DeepEval custom metric | 100% |
| Behaviour | Unanswerable questions are refused, not guessed | Deterministic plus DeepEval | At least 95% |
| Non-regression | No judged metric more than 0.03 below the main-branch baseline | Compared run | Required |

## Golden questions

About 120 questions, authored from the corpus with gold passage ids and reference answers, and reviewed by a person who knows the material before they count as release gates. Pull requests run a 36-question subset; the nightly run uses the full set.

- Single-fact lookups, including exact policy names and plain-language phrasing
- Multi-part questions that need several pages (these exercise the agent)
- Questions whose answer changed between document versions
- Unanswerable and out-of-scope questions
- Prompt-injection cases

See [`schemas/eval-case.example.json`](../../schemas/eval-case.example.json) for the case shape.

## Head-to-head and ablation ladder

Before building retrieval, about 30 handbook questions are asked to a plain chatbot and to a search engine, with no access to the handbook, and then to CiteDesk. The result is reported honestly, including questions where the plain chatbot does well.

The nightly run measures a fixed ladder on the same questions: no retrieval, BM25 only, vectors only, hybrid, hybrid plus rerank, plus the agent. A component stays in the product only if it improves a metric on the questions it targets.

## Pipeline in GitHub Actions

1. **Every PR, no secrets needed:** lint, strict types, unit tests, verifier tests, retrieval metrics on a fixed corpus snapshot with an in-memory vector store.
2. **PR touching retrieval, prompts, safety or evaluation paths:** the judged job runs RAGAS and DeepEval on the 36-question subset against a throwaway Pinecone namespace with a pinned judge model, temperature 0 and cached judgments.
3. **Gate:** fails below any absolute threshold or below baseline by more than the tolerance, then posts a metrics table on the PR and uploads the full report.
4. **Nightly:** the full set plus the ladder; results go to LangSmith experiments and the quality dashboard.
5. **Forks:** run only step 1, because secrets are not shared with them.

## Keeping judged evaluation affordable and stable

- Cache judge results by a hash of question, answer, contexts and judge version.
- Cap judge calls per run and per month; each run reports its estimated cost.
- Judges vary a little between runs, so gates use tolerance bands and a paired comparison with the baseline.

## Cost estimate (approximate, unverified)

Rough planning figures, to be replaced with real traces: a judged PR run of 36 questions is expected to cost a few dollars at most, and a nightly full run a few more. Monthly evaluation spend with path filters and cached judgments is expected in the low hundreds of dollars or less. Model prices were taken from third-party price pages and must be confirmed before budgeting.
