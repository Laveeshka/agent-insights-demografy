"""Validators that score an agent's query result against golden-dataset ground truth.

Each validator compares the ground-truth rows (produced by running a golden
question's ``expected_sql`` directly against BigQuery) with the agent's own
result rows. The two sides can use different column aliases -- the agent
generates its own SQL -- so validators compare by *value*, not by column
name: string values are treated as row identifiers (suburb/state names),
numeric values as the metric the question is actually asking about.
"""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Number
from typing import Any


@dataclass
class ValidationResult:
    passed: bool
    detail: str
    expected_summary: Any
    actual_summary: Any


def _row_strings(row: dict) -> list[str]:
    return [v for v in row.values() if isinstance(v, str)]


def _row_numbers(row: dict) -> list[float]:
    return [
        float(v)
        for v in row.values()
        if isinstance(v, Number) and not isinstance(v, bool)
    ]


def _identifiers(rows: list[dict]) -> list[str]:
    """First string value per row -- the suburb/state name a question is about."""
    ids = []
    for row in rows:
        strings = _row_strings(row)
        if strings:
            ids.append(strings[0])
    return ids


def _first_number(rows: list[dict]) -> float | None:
    for row in rows:
        numbers = _row_numbers(row)
        if numbers:
            return numbers[0]
    return None


def validate_exact_match(expected_rows: list[dict], actual_rows: list[dict], **_) -> ValidationResult:
    """The set of identifiers returned must match exactly (order-independent)."""
    expected_ids = set(_identifiers(expected_rows))
    actual_ids = set(_identifiers(actual_rows))
    passed = bool(expected_ids) and expected_ids == actual_ids
    return ValidationResult(
        passed=passed,
        detail="identifier sets must match exactly",
        expected_summary=sorted(expected_ids),
        actual_summary=sorted(actual_ids),
    )


def validate_ordering(expected_rows: list[dict], actual_rows: list[dict], **_) -> ValidationResult:
    """The relative rank order of identifiers common to both sides must match.

    Restricted to the overlap (rather than requiring identical lists) so a
    correct ranking still passes even if the agent returned a different LIMIT.
    """
    expected_ids = _identifiers(expected_rows)
    actual_ids = _identifiers(actual_rows)
    expected_common = [i for i in expected_ids if i in actual_ids]
    actual_common = [i for i in actual_ids if i in expected_ids]
    passed = bool(expected_common) and expected_common == actual_common
    return ValidationResult(
        passed=passed,
        detail="relative order of overlapping identifiers must match",
        expected_summary=expected_ids,
        actual_summary=actual_ids,
    )


def validate_tolerance(
    expected_rows: list[dict], actual_rows: list[dict], tolerance_pct: float = 1.0, **_
) -> ValidationResult:
    """A single numeric value (an AVG or COUNT) must be within an absolute tolerance.

    ``tolerance_pct`` is an absolute-points tolerance (the KPI columns are
    already on a 0-100 or 0-1 scale), not a relative percentage. 0 means an
    exact match is required -- used for COUNT questions.
    """
    expected_value = _first_number(expected_rows)
    actual_value = _first_number(actual_rows)
    if expected_value is None or actual_value is None:
        return ValidationResult(
            passed=False,
            detail="missing numeric value on one side",
            expected_summary=expected_value,
            actual_summary=actual_value,
        )
    passed = abs(expected_value - actual_value) <= tolerance_pct
    return ValidationResult(
        passed=passed,
        detail=f"|expected - actual| must be <= {tolerance_pct}",
        expected_summary=expected_value,
        actual_summary=actual_value,
    )


def validate_state_match(expected_rows: list[dict], actual_rows: list[dict], **_) -> ValidationResult:
    """The single categorical answer (e.g. a state name) must match, case-insensitively."""
    expected_ids = _identifiers(expected_rows)
    actual_ids = _identifiers(actual_rows)
    expected_value = expected_ids[0] if expected_ids else None
    actual_value = actual_ids[0] if actual_ids else None
    passed = (
        expected_value is not None
        and actual_value is not None
        and expected_value.strip().lower() == actual_value.strip().lower()
    )
    return ValidationResult(
        passed=passed,
        detail="top identifier must match",
        expected_summary=expected_value,
        actual_summary=actual_value,
    )


def validate_row_count(
    expected_rows: list[dict], actual_rows: list[dict], count_tolerance: int = 5, **_
) -> ValidationResult:
    """Row counts must be close, and the returned rows must mostly agree with ground truth."""
    expected_count = len(expected_rows)
    actual_count = len(actual_rows)
    expected_ids = set(_identifiers(expected_rows))
    actual_ids = set(_identifiers(actual_rows))
    overlap = len(expected_ids & actual_ids) / len(expected_ids) if expected_ids else 0.0
    passed = abs(expected_count - actual_count) <= count_tolerance and overlap >= 0.6
    return ValidationResult(
        passed=passed,
        detail=f"row counts within {count_tolerance} and >=60% identifier overlap",
        expected_summary=f"{expected_count} rows",
        actual_summary=f"{actual_count} rows ({overlap:.0%} overlap with ground truth)",
    )


VALIDATORS = {
    "exact_match": validate_exact_match,
    "ordering": validate_ordering,
    "tolerance": validate_tolerance,
    "state_match": validate_state_match,
    "row_count": validate_row_count,
}
