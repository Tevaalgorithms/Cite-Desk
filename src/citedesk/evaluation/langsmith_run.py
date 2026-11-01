"""Run the golden dataset through CiteDesk as a LangSmith experiment.

    uv run python -m citedesk.evaluation.langsmith_run --prefix baseline

Each case becomes one trace (the LangGraph run, the retrieve step and the model call as child runs)
with the case id, prompt version and expected and predicted answers as metadata. The code graders,
the faithfulness judge and the latency and cost numbers are stored as scores on that trace. The
baseline and the improved run use the same dataset version and the same schema, so they compare
directly in LangSmith. A case-level CSV per run is written to evals/results/runs for the report.

Cases run one at a time so that the token count read from the model meter belongs to one question.
"""

import argparse
import csv
import math
import statistics
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from langsmith import Client
from langsmith.evaluation import EvaluationResult
from langsmith.run_helpers import get_current_run_tree
from langsmith.schemas import Example, Run
from openai import OpenAI

from citedesk.bootstrap import App
from citedesk.config import Settings
from citedesk.evaluation.graders import GRADERS, answer_key, answer_view
from citedesk.evaluation.judge import (
    JUDGE_MODEL,
    JUDGE_PROMPT_VERSION,
    FaithfulnessJudge,
)
from citedesk.evaluation.runner import build_sample_app

DATASET = "citedesk-golden"
DATASET_VERSION = "v1"
HANDBOOK = Path("data/sample/acme-handbook.md")

# gpt-5.4-nano list prices in dollars per million tokens, as recorded in
# docs/evaluation/evaluation-strategy.md. Re-check them before relying on a cost figure.
INPUT_USD_PER_MILLION = 0.20
OUTPUT_USD_PER_MILLION = 1.25

Evaluator = Callable[..., dict[str, Any]]


def make_target(
    app: App, cases: Mapping[str, Mapping[str, Any]], prompt_version: str
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """The function LangSmith calls once per case: ask the app and report what happened."""

    def target(inputs: dict[str, Any]) -> dict[str, Any]:
        question = str(inputs["question"])
        case = cases.get(question, {})
        trace = get_current_run_tree()
        if trace is not None:
            trace.add_metadata(
                {
                    "case_id": case.get("case_id", "unknown"),
                    "scenario_type": case.get("scenario_type", "unknown"),
                    "prompt_version": prompt_version,
                    "expected_behavior": case.get("expected_behavior", ""),
                    "expected_answer": case.get("reference_answer", ""),
                }
            )
        before = app.model.usage()
        started = time.monotonic()
        answer = app.answers.ask(question)
        latency = time.monotonic() - started
        after = app.model.usage()

        prompt = (after.prompt_tokens if after else 0) - (before.prompt_tokens if before else 0)
        completion = (after.completion_tokens if after else 0) - (
            before.completion_tokens if before else 0
        )
        cost = (prompt * INPUT_USD_PER_MILLION + completion * OUTPUT_USD_PER_MILLION) / 1_000_000
        citations = sorted(answer.citations, key=lambda citation: citation.marker)
        outputs: dict[str, Any] = {
            "text": answer.text,
            "refused": answer.refused,
            "refusal_reason": answer.refusal_reason,
            "markers": [citation.marker for citation in citations],
            "sections": [citation.section_path for citation in citations],
            "quotes": [citation.quote for citation in citations],
            "latency_s": round(latency, 3),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cost_usd": round(cost, 6),
        }
        if trace is not None:
            trace.add_metadata({"predicted_answer": answer.text, "refused": answer.refused})
        return outputs

    return target


# --- evaluators (scores stored on each trace) ------------------------------------------------


def code_evaluator(name: str) -> Evaluator:
    def evaluate(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
        grade = GRADERS[name](answer_view(outputs), answer_key(reference_outputs))
        return {"key": name, "score": grade.score, "comment": grade.comment}

    return evaluate


def correct(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    """The headline check: every code grader that applies to this case passes."""
    view, key = answer_view(outputs), answer_key(reference_outputs)
    grades = {name: grader(view, key) for name, grader in GRADERS.items()}
    failed = [name for name, grade in grades.items() if grade.score == 0.0]
    return {
        "key": "correct",
        "score": 0.0 if failed else 1.0,
        "comment": f"failed: {failed}" if failed else "all applicable checks passed",
    }


def faithfulness_evaluator(judge: FaithfulnessJudge) -> Evaluator:
    def evaluate(
        inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
    ) -> dict[str, Any]:
        if outputs["refused"] or not outputs["quotes"]:
            return {"key": "faithfulness", "score": None, "comment": "no answer to judge"}
        passages = dict(zip(outputs["markers"], outputs["quotes"], strict=True))
        verdict = judge.judge(inputs["question"], outputs["text"], passages)
        return {"key": "faithfulness", "score": verdict.score, "comment": verdict.reasoning}

    return evaluate


def latency(outputs: dict[str, Any]) -> dict[str, Any]:
    return {"key": "latency_s", "score": outputs["latency_s"]}


def cost(outputs: dict[str, Any]) -> dict[str, Any]:
    return {"key": "cost_usd", "score": outputs["cost_usd"]}


def percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def summary_latency_p95(runs: list[Run], examples: list[Example]) -> EvaluationResult:
    values = [run.outputs["latency_s"] for run in runs if run.outputs]
    return EvaluationResult(key="latency_p95_s", score=percentile(values, 0.95))


def summary_latency_p50(runs: list[Run], examples: list[Example]) -> EvaluationResult:
    values = [run.outputs["latency_s"] for run in runs if run.outputs]
    return EvaluationResult(key="latency_p50_s", score=statistics.median(values))


# --- running ---------------------------------------------------------------------------------


def load_cases(client: Client) -> tuple[list[Any], dict[str, dict[str, Any]]]:
    examples = list(client.list_examples(dataset_name=DATASET, as_of=DATASET_VERSION))
    by_question = {
        str((example.inputs or {})["question"]): {
            **(example.outputs or {}),
            **(example.metadata or {}),
        }
        for example in examples
    }
    return examples, by_question


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Average each score overall and per scenario type, skipping cases where it did not apply."""
    buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for key, score in row["scores"].items():
            if score is not None:
                buckets[key]["all"].append(score)
                buckets[key][row["scenario_type"]].append(score)
    return {
        key: {group: round(statistics.mean(values), 6) for group, values in groups.items()}
        for key, groups in buckets.items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="langsmith_run")
    parser.add_argument("--prefix", required=True, help="experiment name prefix, e.g. baseline")
    parser.add_argument(
        "--limit", type=int, default=None, help="only the first N cases (smoke test)"
    )
    parser.add_argument("--writer-model", default=None, help="override CITEDESK_OPENAI_MODEL")
    parser.add_argument("--out", type=Path, default=Path("evals/results/runs"))
    args = parser.parse_args(argv)

    settings = Settings()
    if settings.langsmith_api_key is None or settings.openai_api_key is None:
        raise SystemExit("Set CITEDESK_LANGSMITH_API_KEY and CITEDESK_OPENAI_API_KEY in .env.")
    client = Client(api_key=settings.langsmith_api_key.get_secret_value())
    examples, cases = load_cases(client)
    if args.limit:
        examples = examples[: args.limit]

    overrides: dict[str, Any] = {
        "writer": "openai",
        "langsmith_tracing": True,
        "langsmith_project": "citedesk-eval",
    }
    if args.writer_model:
        overrides["openai_model"] = args.writer_model
    judge = FaithfulnessJudge(OpenAI(api_key=settings.openai_api_key.get_secret_value()))

    with tempfile.TemporaryDirectory() as folder:
        app = build_sample_app("local", HANDBOOK, Path(folder), **overrides)
        info = app.model.info()
        results = client.evaluate(
            make_target(app, cases, app.prompt_version),
            data=examples,
            evaluators=[code_evaluator(name) for name in GRADERS]
            + [correct, faithfulness_evaluator(judge), latency, cost],
            summary_evaluators=[summary_latency_p50, summary_latency_p95],
            experiment_prefix=args.prefix,
            max_concurrency=1,
            metadata={
                "dataset": DATASET,
                "dataset_version": DATASET_VERSION,
                "prompt_version": app.prompt_version,
                "writer_model": info.model,
                "judge_model": JUDGE_MODEL,
                "judge_prompt_version": JUDGE_PROMPT_VERSION,
                "models": "local",
            },
        )
        rows = _collect(results)
        experiment = results.experiment_name
    client.flush()

    args.out.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out / f"{args.prefix}.csv", rows)
    summary = summarize(rows)
    print(f"experiment: {experiment}  ({len(rows)} cases)")
    for key in sorted(summary):
        print(f"  {key:22} {summary[key]}")
    return 0


def _collect(results: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results:
        run, example = item["run"], item["example"]
        outputs = run.outputs or {}
        scores: dict[str, float | None] = {}
        comments: dict[str, str] = {}
        for result in item["evaluation_results"]["results"]:
            scores[result.key] = result.score
            comments[result.key] = result.comment or ""
        rows.append(
            {
                "case_id": (example.metadata or {}).get("case_id", ""),
                "scenario_type": (example.metadata or {}).get("scenario_type", ""),
                "question": (example.inputs or {}).get("question", ""),
                "expected": (example.outputs or {}).get("reference_answer", ""),
                "predicted": outputs.get("text", ""),
                "refused": outputs.get("refused", ""),
                "scores": scores,
                "comments": comments,
                "latency_s": outputs.get("latency_s", ""),
                "prompt_tokens": outputs.get("prompt_tokens", ""),
                "completion_tokens": outputs.get("completion_tokens", ""),
                "cost_usd": outputs.get("cost_usd", ""),
                "run_id": str(run.id),
            }
        )
    return sorted(rows, key=lambda row: str(row["case_id"]))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    # latency and cost already have their own columns
    score_keys = sorted({key for row in rows for key in row["scores"]} - {"latency_s", "cost_usd"})
    head = ["case_id", "scenario_type", "question", "expected", "predicted", "refused"]
    tail = ["latency_s", "prompt_tokens", "completion_tokens", "cost_usd", "run_id"]
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([*head, *score_keys, "failure_notes", *tail])
        for row in rows:
            notes = "; ".join(
                f"{key}: {row['comments'][key]}"
                for key in score_keys
                if row["scores"].get(key) == 0.0
            )
            writer.writerow(
                [row[name] for name in head]
                + [row["scores"].get(key, "") for key in score_keys]
                + [notes]
                + [row[name] for name in tail]
            )


if __name__ == "__main__":
    raise SystemExit(main())
