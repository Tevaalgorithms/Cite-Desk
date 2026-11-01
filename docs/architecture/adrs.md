# CiteDesk — Architecture Decision Records

Status key: **Accepted** (decided), **Proposed** (recommended, needs confirmation), **Open** (undecided).

## ADR-001 — Use RAG over the handbook, with a stated falsifier
**Accepted.** The handbook is an organization's own, changing text, and users need checkable citations. The decision is falsifiable: the head-to-head against a plain chatbot must show an advantage on handbook-specific questions, or the scope is revisited.

## ADR-002 — Hybrid retrieval with in-process BM25 and Pinecone
**Accepted.** BM25 handles exact policy and form names; vectors handle plain-language phrasing. Results are fused with Reciprocal Rank Fusion (k=60). Consequence: each worker must load the same corpus version; revisit at about a million chunks.

## ADR-003 — Cross-encoder reranking
**Accepted.** Rerank the top 30 fused candidates and keep the best 6 (configurable). Local model by default; adds a few hundred milliseconds.

## ADR-004 — Model provider and data handling
**Open.** OpenAI behind an interface is the working assumption. Before any real or confidential documents are loaded, decide hosted versus self-hosted models and retention settings. Until then only public or synthetic documents are used.

## ADR-005 — No Graph RAG; bounded agent only if it earns its place
**Accepted; the agent question is settled by ADR-018.** A handbook is mostly prose with page and section links, so a graph adds little. The optional agent (max 4 steps, 6 retrievals, 15 seconds) is kept only if the multi-step evaluation shows a gain. Revisit Graph RAG only if questions appear that cannot be answered otherwise.

## ADR-006 — No per-document access control in the MVP
**Proposed.** The MVP assumes one handbook readable by all signed-in employees. Per-document access groups, tenant isolation and leak tests are a later extension; if added, filters must apply inside retrieval before ranking.

## ADR-007 — Citation enforcement by deterministic verifier
**Accepted.** Every sentence needs a valid marker; quotes, numbers, dates and names must appear in the cited passage. One stricter retry, then refusal. Status lines come from code.

## ADR-008 — Evaluation gates are calibrated, not guessed
**Accepted.** Starting thresholds are guesses and are calibrated on the first baseline, then ratcheted up. They are never loosened to pass a failing run. Judged evaluation uses a pinned judge, temperature 0, cached judgments and call caps.

## ADR-009 — Modular monolith, Docker Compose first
**Accepted.** One FastAPI service with background workers; a single host for the MVP. Managed containers and databases come only when uptime or traffic requires them.

## ADR-010 — Exact-key answer cache only
**Accepted.** Cache key includes the normalized question, corpus version and prompt and model versions. No semantic answer caching in the MVP.

## ADR-011 — Corpus licensing gate
**Accepted.** No document is ingested until its license and terms URL are recorded and an admin marks it publishable. Restricted sources cannot be published.

## ADR-012 — Offline stand-ins until the real adapters exist
**Accepted.** The first implementation uses a hashing embedder, an in-memory vector index, a word-overlap reranker and an extractive answer writer so everything runs and tests offline. They are labelled as stand-ins in code. Retrieval and answer quality must not be judged until the Pinecone index, a real embedding model, a cross-encoder and an LLM writer replace them. The relevance threshold (`min_relevance`) is tuned to the overlap reranker and must be recalibrated with the cross-encoder. The default (0.5: a passage must cover at least half of the question's content words) is deliberately strict: with the stand-ins, rephrased questions are refused rather than answered from a loosely matching passage. This means the sample handbook only answers questions that reuse its wording.

## ADR-013 — One SQL repository for SQLite and Postgres
**Accepted.** SQLAlchemy serves SQLite for local work and tests, and Postgres (a free-tier managed instance is the intended first deployment) through the connection URL. The workflow is tested on both: `tests/integration` runs it against Postgres 16 (a CI job and a local Docker container). That run caught a bug SQLite had hidden (chunks inserted before their document); SQLite now enforces foreign keys too. Table creation at startup stands in for migrations, which are a later ticket. Pinecone remains a rebuildable copy, not the system of record.

## ADR-014 — Verification checks faithfulness, not relevance
**Accepted.** The citation verifier proves every sentence is supported by the passage it cites. It cannot tell whether the cited passage answers the question, so relevance is enforced separately (reranker score threshold, and the writer using only passages close to the best match). A test caught an unrelated passage passing verification; it is now a regression test.

## ADR-015 — MVP hosting on a single Lightsail instance
**Accepted.** The MVP runs on one Amazon Lightsail instance with Docker Compose, chosen for low, flat cost and minimal operations (starting plan $12 per month for 2 GB RAM, from AWS's pricing page read on 2026-10-17). Consequences: a single point of failure and downtime during deploys, accepted for the MVP. Secrets use a root-only environment file written by the deploy job, because Lightsail instance identity for SSM is unconfirmed. The database is an external free-tier Postgres, a Lightsail managed database ($15 per month and engine to be confirmed), or SQLite for a first single-instance deployment; the choice is still open. Move to ECS when more than one instance, zero-downtime deploys or role-based secrets are needed. Supersedes the "Hosting target" open question.

## ADR-016 — Local models, raw reranker scores, and held-out evaluation
**Accepted.** A `local` backend runs a real embedding model (BAAI/bge-small-en-v1.5) and cross-encoder (ms-marco MiniLM) on the developer's machine through fastembed, with no API key (`uv sync --extra models`). The `offline` stand-ins stay as the default so tests and CI need no downloads. The cross-encoder's score is kept raw (a logit, typically between about -12 and +8), so the relevance threshold is set per backend and is calibrated with `citedesk eval-retrieval`, never copied between backends. Calibrated on the sample handbook at -10.0 for `local`: it refuses every known unanswerable question at the cost of the two hardest paraphrases. Evaluation uses three question sets so the headline number is honest: `golden` (used to calibrate), `heldout` (used for diagnosis, so now a validation set) and `test` (run once, not gated, to avoid tuning on it). Known limit: a relevance score measures topical closeness, not whether the answer exists, so an unanswerable question about a topic the handbook covers (for example "How much does the cafeteria lunch cost?") can still be answered from the nearby passage. The language-model writer and RAGAS answer-relevancy checks are the planned defence. The extractive writer quotes only the best passage because adding sentences from lower-ranked passages cited unrelated sections.

## ADR-017 — OpenAI answer writer, cheap model by default, model as a setting
**Accepted.** The answer text is written by an OpenAI model (`CITEDESK_WRITER=openai`) that is told to use only the numbered passages, to cite every sentence, and to reply `NO_ANSWER` when the passages do not answer. Its output is never trusted: the deterministic citation verifier still checks every sentence, and `NO_ANSWER`, an unreachable model and unverifiable drafts each become a distinct honest refusal (`passages_do_not_answer`, `model_unavailable`, `could_not_verify_answer`). The default model is `gpt-5.4-nano`, chosen by measurement (see the evaluation strategy), and the model name is a setting (`CITEDESK_OPENAI_MODEL`, stored in SSM as a plain `String` parameter), so changing it needs no code change. The built-in quoting writer stays the default so the project runs with no key and no cost. The web app shows the active model and a "Check connection" button; the check makes one tiny real request, and the server reuses a recent result (never fresher than 15 seconds, 5 minutes on page load) so neither page loads nor clicks can run up the bill. Consequences: answers now depend on a third-party service (its outages become a clear "model unavailable" message), and question text and passages are sent to OpenAI (see ADR-004).

## ADR-018 — No agent loop: measured, not needed on this corpus (refines ADR-005)
**Accepted.** The plan said a bounded agent (split a question into sub-searches) stays only if it measurably helps. It was not built, because the baseline left nothing for it to fix. On 12 multi-part questions ("I am leaving and have a company laptop: what do I do?") written to need two or three handbook sections, plain hybrid retrieval handed the writer every needed section for **12 of 12**; an agent can only improve results when retrieval misses something. The writer then covered all needed sections for 11 of 12 (`gpt-5.4-nano`) and 10 of 12 (`gpt-5.4-mini`); one miss is a flaw in the test question (parental leave was context, not something to look up) and the other is the writer choosing to cite one section, which more searching cannot fix. The built-in quoting writer scored 0 of 12 because it can only quote one sentence, so what handles multi-part questions is the language model, not an agent. Revisit when the corpus is much larger: `citedesk eval-retrieval --golden evals/sample/multistep.json` reports **coverage** (does retrieval reach every needed section) and it is gated in `evals/baselines.json`, so a drop is the signal that an agent has become worth building. Graph RAG remains out (ADR-005). Limits of this evidence: 15 chunks, 12 questions written by the author of the handbook.

## ADR-019 — Pinecone as a rebuildable index; namespaces per environment
**Accepted.** Vectors live in a Pinecone serverless index (`cite-desk`, 384 numbers, cosine, AWS us-east-1) selected with `CITEDESK_VECTOR_INDEX=pinecone`. The database stays the source of truth: at every start `sync_vector_index` adds missing vectors and removes extra ones, so the index can be lost or drift without data loss. Pinecone is eventually consistent, and testing against the real service showed it applies deletes late too, so writes and deletes both wait until the change is visible, and the answer flow only trusts ids that are published. One namespace per environment (`CITEDESK_ENVIRONMENT`, default `dev`; production uses `prod`) keeps development and production apart. Evaluations always use an in-memory index, because syncing against a real namespace from a throwaway database would delete its vectors (a regression test covers this).

## ADR-020 — Tracing is opt-in; the answer cache is exact-match and versioned
**Accepted.** LangSmith tracing (`CITEDESK_LANGSMITH_TRACING=true`) records each answer's steps, timings and model call, but a trace contains the question and, unless `CITEDESK_LANGSMITH_HIDE_CONTENT=true`, the handbook passages, which leaves this system for a third party; so it is off by default and must be chosen per environment (see ADR-004 for real documents). The answer cache is in memory and exact-match, keyed on the question, the corpus version and a label for the writer, model and threshold, so publishing, unpublishing or switching models stops old answers being served. It never stores a model outage or an answer that failed verification. It lives in one process, which is another reason the MVP runs one API container.

## ADR-021 — A revised document replaces the old one in a single swap
**Accepted.** A changed policy used to arrive as a new document while the old one stayed published, so both were searchable and the assistant could confidently cite the outdated text (the citation checker cannot catch that, because the old text really says what it quotes). `replace` takes the new content for a published document and swaps them: the new version is added as a draft (title, source and license carry over unless given), its vectors are written first (searches ignore vectors of unpublished documents), then one database transaction retires the old and publishes the new, bumping the corpus version once. Only then are the old vectors deleted; if that fails the swap still stands, because leftovers are ignored by searches and removed by the repair at start. If anything fails before the swap, the new vectors are removed and the old version stays live. We chose a new document id over editing in place so old citations stay traceable in the audit log (`replaced_by:<id>` on the old, `replaces:<id>` on the new) and the existing publish and unpublish paths are reused; no schema change was needed. Not built: showing a diff between the versions, and replacing a document that is not published (publish or add it instead).

## ADR-023 — A lower relevance cutoff is recommended only with the language-model writer
**Proposed, for review.** The Week 4 evaluation (40 reviewed questions, LangSmith dataset `citedesk-golden` v1, three runs per setting) found that `CITEDESK_MIN_RELEVANCE=-10.5` instead of the default -10.0 fixes one answerable question that was refused (`gv1-033`, score -10.29) and raised the share of cases passing every code check from 0.917 to 0.950, with the language-model writer (`gpt-5.4-nano`). Faithfulness did not change (0.933 to 0.935, inside the 0.90 to 0.97 spread of identical runs). With the real writer, none of the 14 unanswerable sample questions was answered at either value.

The default stays -10.0 because the quality gate for the built-in quoting writer fails at -10.5: `confidently_wrong` rose from 0 to 2 and `unanswerable_answered` from 0 to 1 on `golden`. That writer cannot refuse on its own, so a lower cutoff lets a question such as the guest wifi password (score -10.01) reach it. The gate and `evals/baselines.json` were not changed.

What the evidence does not show: the benefit rests on the two questions that exposed the problem (`gv1-033`, and `gv1-034`, whose right section ranks second at -10.51 and is still lost). No other sample question scores below -6.1, so the cutoff is not validated on a larger or real handbook. A reviewer could instead make the cutoff depend on the writer; that is a design change and was not made.

Also tried and rejected in the same evaluation, so they are not repeated: a prompt rule against added commentary (no net faithfulness gain, one case fixed and another broken, about 11% more cost per question than the cutoff change alone), a prompt rule allowing partial answers (faithfulness fell), and a retry message telling the writer not to repeat numbers from the question (it repeated them anyway). Loosening the verifier to accept numbers from the question was not tried, because it weakens a safety check. Details: `evals/results/improvements-report.md`.

## Open questions

1. Which corpus (see dataset feasibility) and under what attribution?
2. Who reviews the golden questions?
3. OpenAI only, or also Claude behind the same interface?
4. Which Postgres (free-tier provider, Lightsail managed database, or SQLite first), and the evaluation budget cap.
