"""Custom agent tools.

Add formatting helpers or chart generation utilities here.
"""

def format_table_rows(rows):
    """Convert DB rows into a simple text block for display (placeholder)."""
    out_lines = []
    for r in rows:
        out_lines.append(str(r))
    return "\n".join(out_lines)
