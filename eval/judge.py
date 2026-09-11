"""LLM-as-a-judge scoring.

Uses Gemini to score the SQL agent's natural-language answer against the
question and the ground-truth rows, following the 1-5 rubric.
"""
from __future__ import annotations

import logging
import os
import re

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

logger = logging.getLogger(__name__)

_RUBRIC = """You are grading a demographic data chatbot's answer for accuracy.

Score the CANDIDATE ANSWER on a 1-5 scale using GROUND TRUTH DATA as the source of truth:
5 = perfect match with correct data
4 = correct data, minor formatting issues
3 = mostly correct, small discrepancies
2 = partially correct, significant errors
1 = wrong answer, missing data, or failed to answer

Respond with exactly two lines and nothing else:
SCORE: <1-5>
RATIONALE: <one sentence explaining the score>"""

_judge_llm: ChatGoogleGenerativeAI | None = None

def _get_judge_llm() -> ChatGoogleGenerativeAI:
    global _judge_llm
    if _judge_llm is None:
        _judge_llm = ChatGoogleGenerativeAI(
            model="gemini-3.5-flash-lite",
            google_api_key=os.getenv("GEMINI_API_KEY"),
        )
    return _judge_llm

def _format_ground_truth(expected_rows: list[dict]) -> str:
    if not expected_rows:
        return "(no rows)"
    lines = [", ".join(f"{k}={v}" for k, v in row.items()) for row in expected_rows[:10]]
    return "\n".join(lines)

def _invoke_text(llm: ChatGoogleGenerativeAI, prompt: str) -> str:
    response = llm.invoke(prompt)
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)

def _parse_score(text: str) -> tuple[int, str, str]:
    """Return (score, rationale, status). status is "scored" only when a real SCORE line was found."""
    score_match = re.search(r"SCORE:\s*([1-5])", text, re.IGNORECASE)
    rationale_match = re.search(r"RATIONALE:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if not score_match:
        logger.warning("Judge response had no parseable SCORE line: %r", text[:300])
        rationale = rationale_match.group(1).strip() if rationale_match else text.strip()[:300]
        return 1, f"[unparseable judge response, defaulted to 1] {rationale}", "parse_error"
    rationale = rationale_match.group(1).strip() if rationale_match else text.strip()[:300]
    return int(score_match.group(1)), rationale, "scored"

def score_response(question: str, expected_rows: list[dict], actual_answer: str) -> dict:
    """Return {"score": 1-5, "rationale": str, "status": str} comparing ground truth vs the agent's answer.

    ``status`` distinguishes a genuine judge verdict from a fallback score of 1
    standing in for a missing judgment. Callers should exclude every non-"scored"
    status from aggregate averages, since those 1s say nothing about answer
    quality -- they just mean no real judgment could be made:

    - "scored": Gemini returned a parseable SCORE line. The score is a real
      1-5 verdict on answer quality.
    - "no_answer": the SQL agent itself produced an empty/blank answer, so the
      judge was never called -- there was nothing to grade.
    - "parse_error": the judge responded, but its text had no `SCORE: <1-5>`
      line the regex could extract (e.g. it ignored the format). The
      rationale still contains whatever text the judge sent back.
    - "invocation_error": calling the judge LLM raised an exception (e.g.
      network failure, rate limit, auth error) before any response arrived.
    """
    if not actual_answer or not actual_answer.strip():
        return {"score": 1, "rationale": "agent produced no answer", "status": "no_answer"}

    prompt = (
        f"{_RUBRIC}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"GROUND TRUTH DATA (correct rows from the database):\n{_format_ground_truth(expected_rows)}\n\n"
        f"CANDIDATE ANSWER (from the agent being evaluated):\n{actual_answer}"
    )
    try:
        text = _invoke_text(_get_judge_llm(), prompt)
        score, rationale, status = _parse_score(text)
    except Exception as exc:
        logger.warning("Judge invocation failed", exc_info=True)
        return {"score": 1, "rationale": f"judge invocation failed: {exc}", "status": "invocation_error"}

    return {"score": score, "rationale": rationale, "status": status}
