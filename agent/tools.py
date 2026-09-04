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


def validate_read_only_sql(
    sql: str,
    required_table: str | None = None,
    require_column_aliases: bool = False,
) -> bool:
    """Return whether SQL meets the configured read-only query constraints."""
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
    if re.search(blocked, without_terminal_semicolon, re.IGNORECASE):
        return False

    if required_table and not _uses_required_table(without_terminal_semicolon, required_table):
        return False

    if require_column_aliases and not _has_column_aliases(without_terminal_semicolon):
        return False

    return True


def _uses_required_table(sql: str, required_table: str) -> bool:
    """Require the approved fully qualified table in the query."""
    # Accept optional BigQuery identifier quoting while requiring the exact path.
    table_pattern = re.escape(required_table).replace(r"\.", r"\s*\.\s*")
    return re.search(rf"(?<![\w.])`?{table_pattern}`?(?![\w.])", sql, re.IGNORECASE) is not None


def _has_column_aliases(sql: str) -> bool:
    """Require explicit aliases for every selected expression."""
    select_list = _top_level_select_list(sql)
    if select_list is None:
        return False

    expressions = _split_sql_list(select_list)
    if not expressions:
        return False
    return all(re.search(r"\s+AS\s+[A-Za-z_][\w]*\s*$", expression, re.IGNORECASE) for expression in expressions)


def _top_level_select_list(sql: str) -> str | None:
    """Return the outermost SELECT list without parsing SQL dialects fully."""
    depth = 0
    select_start = None
    from_start = None
    tokens = re.finditer(r"`[^`]*`|'(?:''|[^'])*'|\bSELECT\b|\bFROM\b|[()]", sql, re.IGNORECASE)
    for match in tokens:
        token = match.group(0)
        if token.startswith(("`", "'")):
            continue
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and token.upper() == "SELECT" and select_start is None:
            select_start = match.end()
        elif depth == 0 and token.upper() == "FROM" and select_start is not None:
            from_start = match.start()
            break
    if select_start is None or from_start is None:
        return None
    return sql[select_start:from_start].strip()


def _split_sql_list(value: str) -> list[str]:
    """Split comma-separated SQL expressions while ignoring nested commas."""
    expressions = []
    start = 0
    depth = 0
    quote = None
    for index, character in enumerate(value):
        if quote:
            if character == quote and (index == 0 or value[index - 1] != "\\"):
                quote = None
            continue
        if character in ("'", '"', '`'):
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            expressions.append(value[start:index].strip())
            start = index + 1
    expressions.append(value[start:].strip())
    return [expression for expression in expressions if expression]


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
