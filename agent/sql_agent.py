"""Gemini-backed SQL insight agent with an injected BigQuery boundary."""

import os
import re
import logging

from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

# Load .env so local development credentials (GOOGLE_APPLICATION_CREDENTIALS)
# and GEMINI_API_KEY are available when running locally.
load_dotenv()

from agent.prompts import FEW_SHOT_PREFIX
from agent.tools import (
    clean_generated_sql,
    format_query_results,
    get_schema_context,
    limit_query_results,
    validate_read_only_sql,
)
from eval.tracing import get_tracer


class SQLAgent:
    """Turn natural-language questions into grounded BigQuery answers.

    ``BigQueryClient`` is injected so it owns authentication and database
    access. This agent owns prompting, validation, bounded repair, and answer
    generation, keeping the backend independent from Streamlit.
    """
    # Restrict generated queries to the approved data source.
    TABLE_NAME = "prod_tables.a_master_view"
    # Keep the result context small enough for reliable LLM responses.
    MAX_RESULT_ROWS = 50

    def __init__(self, bigquery_client, llm):
        """Store injected services without creating database connections."""
        # Inject dependencies so this class does not create connections itself.
        self.bigquery_client = bigquery_client
        self.llm = llm
        self.tracer = get_tracer()

    def answer_question(self, question: str) -> dict:
        """Execute one bounded SQL-generation flow and return a UI-safe result."""
        # Return a stable structure that the terminal or Streamlit can consume.
        result = {"answer": None, "sql": None, "rows": [], "error": None}
        question = str(question or "").strip()
        if not question:
            result["error"] = "A question is required."
            return result

        # Supply live schema information alongside the approved prompt guidance.
        schema = self._get_schema()
        schema_context = get_schema_context(schema, self.TABLE_NAME)
        sql = None
        error = ""

        # Allow one repair attempt, but never retry indefinitely.
        for attempt in range(2):
            try:
                if attempt == 0:
                    generated = self._invoke(self._build_sql_prompt(question, schema_context))
                else:
                    generated = self._invoke(
                        self._build_repair_prompt(question, sql, schema_context, error)
                    )
                sql = clean_generated_sql(generated)
            except Exception as exc:
                result["error"] = f"SQL generation failed: {exc}"
                result["sql"] = sql
                return result

            # Trace SQL-generation result (only when tracer enabled)
            if getattr(self.tracer, "enabled", False):
                try:
                    self.tracer.record("sql_generation", {"question": question, "sql": sql})
                except Exception as exc:
                    logging.debug("Tracer record failed (sql_generation): %s", exc, exc_info=True)

            # Reject unsafe SQL before it can reach BigQuery.
            sql = self._enforce_row_limit(sql)
            if not validate_read_only_sql(
                sql,
                required_table=f"demografy.{self.TABLE_NAME}",
                require_column_aliases=True,
            ):
                error = (
                    "Generated SQL is empty, unsafe, missing the approved fully "
                    "qualified table, or missing descriptive column aliases."
                )
                if attempt == 0:
                    continue
                result["error"] = error
                result["sql"] = sql
                return result

            # Execute only SQL that passed the runtime safety check.
            try:
                raw_rows = self.bigquery_client.query(sql)
            except Exception as exc:
                error = str(exc)
                if attempt == 1:
                    result["error"] = f"BigQuery query failed: {error}"
                    result["sql"] = sql
                    return result
                continue

            # Limit and format database data before sending it to Gemini.
            limited_rows = limit_query_results(raw_rows, self.MAX_RESULT_ROWS)
            formatted_rows = format_query_results(limited_rows)
            result["rows"] = self._serializable_rows(limited_rows)
            result["sql"] = sql
            # Trace query results (only when tracer enabled)
            if getattr(self.tracer, "enabled", False):
                try:
                    self.tracer.record("query_result", {"sql": sql, "rows": result["rows"]})
                except Exception as exc:
                    logging.debug("Tracer record failed (query_result): %s", exc, exc_info=True)
            # Generate the final answer from actual query results, not guesses.
            try:
                result["answer"] = self._invoke(
                    self._build_answer_prompt(question, formatted_rows)
                )
                if getattr(self.tracer, "enabled", False):
                    try:
                        self.tracer.record(
                            "answer_generation",
                            {"question": question, "answer": result["answer"]},
                        )
                    except Exception as exc:
                        logging.debug(
                            "Tracer record failed (answer_generation): %s", exc, exc_info=True
                        )
            except Exception as exc:
                result["error"] = f"Answer generation failed: {exc}"
            return result

        result["error"] = "Unable to generate safe SQL."
        result["sql"] = sql
        return result

    def _get_schema(self) -> list[dict] | None:
        """Use the existing client schema interface without adding a connection."""
        # Schema lookup is best-effort so a temporary metadata failure does not stop the agent.
        project = os.getenv("BIGQUERY_PROJECT", "demografy")
        try:
            return self.bigquery_client.get_table_schema(
                f"{project}.{self.TABLE_NAME}"
            )
        except Exception:
            return None

    def _build_sql_prompt(self, question: str, schema_context: str) -> str:
        """Combine approved few-shot guidance with live question context.

        ``prompts.py`` owns the business mappings and SQL-generation rules;
        this module only supplies request-specific context and orchestration.
        """
        return (
            f"{FEW_SHOT_PREFIX}\n\n"
            "LIVE SCHEMA CONTEXT:\n"
            f"{schema_context}\n\n"
            f"USER QUESTION:\n{question}\n\n"
            "Return exactly one read-only BigQuery SQL query and no explanation."
        )

    def _build_repair_prompt(
        self, question: str, failed_sql: str | None, schema_context: str, error: str
    ) -> str:
        """Reuse the approved few-shot guidance when repairing failed SQL."""
        return (
            f"{FEW_SHOT_PREFIX}\n\n"
            "Repair the failed query using the same approved table and mappings. "
            "Return exactly one read-only BigQuery SQL query and no explanation.\n\n"
            f"LIVE SCHEMA CONTEXT:\n{schema_context}\n\n"
            f"USER QUESTION:\n{question}\n"
            f"FAILED SQL:\n{failed_sql or '(none)'}\n"
            f"BIGQUERY ERROR:\n{error}"
        )

    def _build_answer_prompt(self, question: str, formatted_rows: str) -> str:
        # Include actual rows so the natural-language answer remains grounded.
        return (
            "Answer the user using only the actual database result below. "
            "Do not invent values, preserve important numbers, state clearly "
            "when no rows were returned, and be concise. Return text only, "
            "with no charts, code blocks, or machine-readable JSON. If the "
            "user requested more than 50 rows, explain that results are capped "
            "at 50 and suggest narrowing the query with filters.\n\n"
            f"User question: {question}\n\nDatabase result:\n{formatted_rows}"
        )

    def _enforce_row_limit(self, sql: str) -> str:
        """Add or reduce the outer query LIMIT so no more than 50 rows are queried."""
        # Enforce the database-side cap before execution, not only in the LLM context.
        terminal_semicolon = ";" if sql.rstrip().endswith(";") else ""
        body = sql.rstrip().rstrip(";").rstrip()
        limits = list(re.finditer(r"\bLIMIT\s+(\d+)\b", body, re.IGNORECASE))
        if limits:
            match = limits[-1]
            requested_limit = int(match.group(1))
            if requested_limit <= self.MAX_RESULT_ROWS:
                return sql
            body = f"{body[:match.start(1)]}{self.MAX_RESULT_ROWS}{body[match.end(1):]}"
            return body + terminal_semicolon
        return f"{body}\nLIMIT {self.MAX_RESULT_ROWS}{terminal_semicolon}"

    def _invoke(self, prompt: str) -> str:
        # Normalize Gemini response objects into plain text for the backend result.
        response = self.llm.invoke(prompt)
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return str(content)

    @staticmethod
    def _serializable_rows(rows: list) -> list:
        # Convert BigQuery row objects into values that a frontend can serialize.
        serializable = []
        for row in rows:
            if isinstance(row, dict):
                serializable.append(row)
            elif hasattr(row, "items"):
                serializable.append(dict(row.items()))
            else:
                try:
                    serializable.append(dict(row))
                except (TypeError, ValueError):
                    serializable.append(row)
        return serializable


def create_demografy_agent(bigquery_client, llm=None):
    """Create an SQLAgent using an externally constructed BigQueryClient."""
    # Preserve environment-based Gemini authentication while accepting injected test doubles.
    if llm is None:
        llm = ChatGoogleGenerativeAI(
            model="gemini-3.5-flash-lite",
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=0,
        )
    return SQLAgent(bigquery_client, llm)
