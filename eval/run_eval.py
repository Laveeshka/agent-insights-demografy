"""Automated evaluation runner.

Loads `golden_dataset.json`, runs each question through the live SQLAgent,
checks the agent's result against ground truth computed by running each
question's `expected_sql` directly against BigQuery, and asks the LLM judge
to score the agent's natural-language answer. Prints a summary and writes a
full structured report to `eval/eval_report.json`.

Usage: python -m eval.run_eval
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from agent.sql_agent import create_demografy_agent
from db.bigquery_client import BigQueryClient
from eval import judge
from eval.tracing import get_tracer
from eval.validators import VALIDATORS

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"
REPORT_PATH = Path(__file__).parent / "eval_report.json"


def load_golden_dataset() -> list[dict]:
    with open(DATASET_PATH) as f:
        return json.load(f)


def run_expected_query(bq_client: BigQueryClient, expected_sql: str) -> list[dict]:
    return [dict(row) for row in bq_client.query(expected_sql)]


def run_question(bq_client: BigQueryClient, agent, tracer, item: dict) -> dict:
    """Run one golden question end-to-end and return its report row.

    Ground-truth failures and agent failures are caught here (not raised) so
    one bad question never aborts the rest of the eval run.
    """
    result_row = {
        "id": item["id"],
        "question": item["question"],
        "validation_type": item["validation_type"],
    }
    start = time.monotonic()

    try:
        expected_rows = run_expected_query(bq_client, item["expected_sql"])
    except Exception as exc:
        result_row.update(passed=False, error=f"ground truth query failed: {exc}")
        return result_row

    try:
        agent_result = agent.answer_question(item["question"])
    except Exception as exc:
        result_row.update(passed=False, error=f"agent invocation failed: {exc}")
        return result_row

    elapsed = round(time.monotonic() - start, 2)
    result_row["latency_s"] = elapsed
    result_row["actual_sql"] = agent_result.get("sql")

    if agent_result.get("error"):
        result_row.update(passed=False, error=agent_result["error"])
        return result_row

    validator = VALIDATORS[item["validation_type"]]
    validation = validator(
        expected_rows,
        agent_result["rows"],
        tolerance_pct=item.get("tolerance_pct", 1.0),
    )
    judge_result = judge.score_response(
        question=item["question"],
        expected_rows=expected_rows,
        actual_answer=agent_result.get("answer") or "",
    )
    result_row.update(
        passed=validation.passed,
        detail=validation.detail,
        expected=validation.expected_summary,
        actual=validation.actual_summary,
        actual_answer=agent_result.get("answer"),
        judge_score=judge_result.get("score"),
        judge_rationale=judge_result.get("rationale"),
        judge_status=judge_result.get("status"),
    )

    if getattr(tracer, "enabled", False):
        try:
            tracer.record("eval_result", result_row)
        except Exception:
            pass  # Tracing must never fail the eval run itself.

    return result_row


def print_result(row: dict) -> None:
    status = "PASS" if row.get("passed") else "FAIL"
    judge_bit = ""
    if row.get("judge_score") is not None:
        fallback_note = "" if row.get("judge_status") == "scored" else f" [{row['judge_status']}]"
        judge_bit = f", judge {row['judge_score']}/5{fallback_note}"
    print(f"[{status}] Q{row['id']} ({row['latency_s']}s{judge_bit}): {row['question']}")
    if status == "FAIL":
        if row.get("error"):
            print(f"    error:    {row['error']}")
        else:
            print(f"    expected: {row.get('expected')}")
            print(f"    actual:   {row.get('actual')}")


def summarize(results: list[dict]) -> dict:
    passed_count = sum(1 for r in results if r.get("passed"))
    # Only "scored" rows reflect a genuine judge verdict -- "no_answer" /
    # "parse_error" / "invocation_error" are fallback 1s standing in for a
    # missing judgment, and would silently drag the average down if included.
    scored = [r for r in results if r.get("judge_status") == "scored"]
    fallback = [r for r in results if r.get("judge_status") not in (None, "scored")]
    judge_scores = [r["judge_score"] for r in scored]
    return {
        "total": len(results),
        "passed": passed_count,
        "accuracy_pct": round(100 * passed_count / len(results), 1) if results else 0.0,
        "avg_judge_score": round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None,
        "judge_scored_count": len(scored),
        "judge_fallback_count": len(fallback),
        "judge_fallback_question_ids": [r["id"] for r in fallback],
    }


def main() -> None:
    bq_client = BigQueryClient()
    agent = create_demografy_agent(bq_client)
    tracer = get_tracer()
    dataset = load_golden_dataset()

    results = [run_question(bq_client, agent, tracer, item) for item in dataset]
    for row in results:
        print_result(row)

    summary = summarize(results)
    REPORT_PATH.write_text(json.dumps({"summary": summary, "results": results}, indent=2, default=str))

    print()
    print(
        f"{summary['passed']}/{summary['total']} passed ({summary['accuracy_pct']}%), "
        f"avg judge score: {summary['avg_judge_score']} (over {summary['judge_scored_count']} scored)"
    )
    if summary["judge_fallback_count"]:
        print(
            f"  {summary['judge_fallback_count']} judge fallback(s) excluded from the average "
            f"(question ids: {summary['judge_fallback_question_ids']}) -- see judge_status in the report"
        )
    print(f"Full report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
