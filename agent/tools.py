"""Small, dependency-free helpers used by the SQL insight agent."""

import json
import re
from collections.abc import Iterable, Mapping
from numbers import Number


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


def map_agent_result_to_message(result: dict) -> str:
    """Map an agent result dict to a human-friendly message for UI display.

    Expected `result` keys: 'answer', 'sql', 'rows', 'error'. This centralizes
    the UI-friendly mapping so other callers (tests, CLI, UI) can reuse it.
    """
    if not isinstance(result, dict):
        return str(result or "Sorry, something went wrong.")

    raw_error = (result.get("error") or "")
    rows = result.get("rows") or []

    if raw_error:
        lower_err = raw_error.lower()
        if "generated sql is empty" in lower_err or "missing the approved fully qualified table" in lower_err or "missing descriptive column aliases" in lower_err:
            return (
                "I can only answer questions about Demografy's dataset (suburbs, states, and KPI columns). "
                "Try asking something like: 'Top 3 diverse suburbs in VIC' or include a state and KPI name."
            )
        if "bigquery query failed" in lower_err:
            short = raw_error.split(":", 1)[-1].strip() if ":" in raw_error else raw_error
            return f"There was a problem running the database query: {short}. Please try again later."
        if "sql generation failed" in lower_err:
            return (
                "I couldn't generate a safe SQL query for that question. Try rephrasing the question to reference suburbs, states, or KPI names."
            )
        if "answer generation failed" in lower_err:
            return "I couldn't generate a natural-language answer from the query results. Please try again."
        return f"Sorry, I couldn't answer that: {raw_error}"

    # No raw error. If the query returned no rows, show helpful guidance.
    if not rows:
        return (
            "No rows returned. There may be no matching data for that query. "
            "Try broadening filters, checking the state/suburb spelling, or removing restrictive conditions."
        )

    return result.get("answer") or "No answer available."


def has_chart_intent(question: str) -> bool:
    """Return True when the user explicitly asks for a chart or visualization."""
    return bool(
        re.search(
            r"\b(chart|plot|graph|visuali[sz]e|visuali[sz]ation|bar chart|line chart|line graph|scatter plot|scatter chart|pie chart)\b",
            str(question or ""),
            re.IGNORECASE,
        )
    )


def build_chart_data(question: str, rows: list, llm=None) -> dict:
    """Build minimal chart metadata from existing database rows only.

    A chart is generated automatically whenever there are enough rows to make
    one useful (5 or more) -- the user does not need to explicitly ask for a
    chart or graph. ``requested`` is still tracked so the UI can explain when
    an explicit chart request could not be satisfied.
    """
    requested = has_chart_intent(question)
    chart = {
        "requested": requested,
        "enough_rows": False,
        "chart_type": None,
        "data": None,
        "x": None,
        "y": None,
    }
    if len(rows or []) < 5:
        return chart

    first_row = rows[0]
    if not isinstance(first_row, Mapping):
        return chart

    columns = list(first_row.keys())
    numeric_columns = [
        column
        for column in columns
        if isinstance(first_row.get(column), Number) and not isinstance(first_row.get(column), bool)
    ]
    text_columns = [column for column in columns if isinstance(first_row.get(column), str)]
    time_columns = [
        column
        for column in columns
        if re.search(r"\b(date|time|year|month|week|day)\b", str(column), re.IGNORECASE)
    ]
    x_column = text_columns[0] if text_columns else None
    y_column = numeric_columns[0] if numeric_columns else None

    requested_type = _requested_chart_type(question)
    chart_type = requested_type
    if chart_type == "pie":
        chart_type = "bar"
    if chart_type == "scatter" and len(numeric_columns) >= 2:
        x_column = numeric_columns[0]
        y_column = numeric_columns[1]
    elif chart_type == "line" and time_columns and numeric_columns:
        x_column = time_columns[0]
        y_column = numeric_columns[0]
    elif chart_type == "bar" and numeric_columns:
        y_column = numeric_columns[0]
    elif chart_type is None:
        chart_type = _determine_chart_type(time_columns, text_columns, numeric_columns)
        if chart_type is None and llm is not None:
            chart_type = _llm_chart_type(llm, columns)
        if chart_type == "scatter" and len(numeric_columns) >= 2:
            x_column = numeric_columns[0]
            y_column = numeric_columns[1]
        elif chart_type == "line" and time_columns and numeric_columns:
            x_column = time_columns[0]
            y_column = numeric_columns[0]
        elif chart_type == "bar" and numeric_columns:
            y_column = numeric_columns[0]

    if not chart_type or not y_column:
        return chart

    chart.update(
        (
            {
                "enough_rows": True,
                "chart_type": chart_type,
                "data": rows,
                "x": x_column,
                "y": y_column,
            }
        )
    )
    return chart


def _requested_chart_type(question: str) -> str | None:
    text = str(question or "").lower()
    if re.search(r"\bbar chart\b", text):
        return "bar"
    if re.search(r"\bline (chart|graph)\b", text):
        return "line"
    if re.search(r"\bscatter (plot|chart)\b", text):
        return "scatter"
    if re.search(r"\bpie chart\b", text):
        return "pie"
    return None


def _determine_chart_type(time_columns: list, text_columns: list, numeric_columns: list) -> str | None:
    if time_columns and numeric_columns:
        return "line"
    if len(numeric_columns) >= 2 and not text_columns:
        return "scatter"
    if text_columns and numeric_columns:
        return "bar"
    return None


def _llm_chart_type(llm, columns: list) -> str | None:
    prompt = (
        "Choose one chart type for these result columns. "
        "Allowed: bar, line, scatter. Return only one word.\n"
        f"Columns: {', '.join(str(column) for column in columns)}"
    )
    try:
        response = llm.invoke(prompt)
    except Exception:
        return None
    content = getattr(response, "content", response)
    text = str(content).strip().lower()
    return text if text in {"bar", "line", "scatter"} else None


def normalize_assistant_message(content: str) -> str:
    """Convert previously stored assistant message text into the current
    user-friendly form when possible.

    This helps when `st.session_state.messages` contains legacy raw LLM
    outputs (e.g. 'No rows returned.') so the UI shows the mapped, helpful
    guidance without requiring a session restart.
    """
    if not isinstance(content, str) or not content:
        return content

    lower = content.lower().strip()
    # Known legacy phrasing for empty results
    if "no rows returned" in lower or "no rows were returned" in lower:
        return map_agent_result_to_message({"rows": []})

    # Known legacy validation error text
    if (
        "generated sql is empty" in lower
        or "missing the approved fully qualified table" in lower
        or "missing descriptive column aliases" in lower
    ):
        return map_agent_result_to_message({"error": content})

    return content
