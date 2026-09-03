"""Small, dependency-free helpers used by the SQL insight agent."""

import json
import re
from collections.abc import Iterable, Mapping


def get_schema_context(
    schema: list[dict] | None = None,
    table_name: str = "prod_tables.a_master_view",
) -> str:
    """Build truthful schema context for the SQL-generation prompt.

    Schema retrieval remains the responsibility of ``BigQueryClient``. This
    helper only formats supplied metadata and falls back to the approved table
    name when column metadata is unavailable.
    """
    # Format live schema metadata without inventing columns or tables.
    if not schema:
        return (
            f"Approved table: `{table_name}`\n"
            "Column-level schema metadata is unavailable; use only this table "
            "and do not invent column names."
        )

    lines = [f"Approved table: `{table_name}`", "Columns:"]
    for column in schema:
        name = column.get("name", "unknown")
        column_type = column.get("type", "unknown")
        mode = column.get("mode", "")
        description = column.get("description") or ""
        details = " ".join(part for part in (column_type, mode, description) if part)
        lines.append(f"- {name}: {details}".rstrip())
    return "\n".join(lines)


def clean_generated_sql(raw_sql: str) -> str:
    """Remove common Markdown wrappers while preserving SQL semantics."""
    # Remove Markdown wrappers because LLMs may return fenced SQL.
    sql = str(raw_sql or "").strip()
    if sql.startswith("```") and sql.endswith("```"):
        lines = sql.splitlines()
        lines = lines[1:] if lines and lines[0].strip().startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        sql = "\n".join(lines).strip()
    return sql


def validate_read_only_sql(sql: str) -> bool:
    """Return whether SQL is a single, obviously read-only query."""
    # Enforce a runtime read-only boundary because prompt instructions are not security controls.
    statement = str(sql or "").strip()
    if not statement:
        return False

    # Ignore comments and quoted text so words inside them are not treated as
    # executable statements or dangerous SQL keywords.
    inspected = re.sub(r"--[^\n]*|/\*.*?\*/", " ", statement, flags=re.DOTALL)
    inspected = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", "''", inspected)
    stripped = inspected.rstrip()
    without_terminal_semicolon = stripped[:-1].rstrip() if stripped.endswith(";") else stripped
    if ";" in without_terminal_semicolon:
        return False
    if not re.match(r"^(SELECT|WITH)\b", without_terminal_semicolon, re.IGNORECASE):
        return False

    blocked = r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE)\b"
    return re.search(blocked, without_terminal_semicolon, re.IGNORECASE) is None


def limit_query_results(rows: Iterable, max_rows: int = 50) -> list:
    """Limit rows before they enter the LLM context.

    This controls context size and token usage and prevents huge result sets
    from being passed to Gemini; it never changes database values or SQL.
    """
    # Bound the data passed to Gemini to control context size and token usage.
    if max_rows < 0:
        raise ValueError("max_rows must be non-negative")
    return list(rows or [])[:max_rows]


def format_query_results(rows: Iterable) -> str:
    """Format normal, limited, or empty query results for Gemini."""
    # Convert database rows into stable text that Gemini can interpret reliably.
    limited_rows = list(rows or [])
    if not limited_rows:
        return "No rows returned."

    formatted = []
    for row in limited_rows:
        if isinstance(row, Mapping):
            formatted.append(dict(row))
        elif hasattr(row, "items"):
            formatted.append(dict(row.items()))
        else:
            try:
                formatted.append(dict(row))
            except (TypeError, ValueError):
                formatted.append(str(row))
    return json.dumps(formatted, default=str, ensure_ascii=False)
