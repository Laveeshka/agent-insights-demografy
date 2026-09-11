"""LangSmith tracing, enabled only when explicitly opted in via env vars.

Set ``LANGCHAIN_TRACING_V2=true`` plus ``LANGSMITH_API_KEY`` (or the legacy
``LANGCHAIN_API_KEY``) to send events to LangSmith. Missing the SDK, the
opt-in flag, or the API key all resolve to a no-op tracer so callers never
need to branch on whether tracing is active.
"""
from __future__ import annotations

import datetime
import logging
import os
import uuid
from typing import Any, Optional

try:
    from langsmith import Client
except ImportError:
    Client = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in _TRUTHY


class Tracer:
    """Base tracer interface. ``enabled`` lets callers skip work cheaply."""

    enabled = False

    def record(self, event: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class _NoopTracer(Tracer):
    enabled = False

    def record(self, event: str, payload: dict[str, Any]) -> None:
        return None


class _LangSmithTracer(Tracer):
    enabled = True

    def __init__(self, client: "Client", project_name: Optional[str]):
        self._client = client
        self._project_name = project_name

    def record(self, event: str, payload: dict[str, Any]) -> None:
        """Log a completed, instantaneous run. Best-effort: never raises."""
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            self._client.create_run(
                id=uuid.uuid4(),
                name=event,
                run_type="tool",
                inputs=payload,
                start_time=now,
                end_time=now,
                project_name=self._project_name,
            )
        except Exception:
            logger.warning("LangSmith trace for %r failed", event, exc_info=True)


def get_tracer() -> Tracer:
    """Build a tracer from env vars, falling back to a no-op tracer."""
    if not _is_truthy(os.environ.get("LANGCHAIN_TRACING_V2")):
        return _NoopTracer()

    if Client is None:
        logger.warning(
            "LANGCHAIN_TRACING_V2 is set but the `langsmith` package is not installed."
        )
        return _NoopTracer()

    api_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    if not api_key:
        logger.warning(
            "LANGCHAIN_TRACING_V2 is set but no LANGSMITH_API_KEY/LANGCHAIN_API_KEY was found."
        )
        return _NoopTracer()

    api_url = os.environ.get("LANGSMITH_ENDPOINT") or os.environ.get("LANGCHAIN_ENDPOINT")
    project_name = os.environ.get("LANGSMITH_PROJECT") or os.environ.get("LANGCHAIN_PROJECT")

    try:
        client = Client(api_key=api_key, api_url=api_url)
    except Exception:
        logger.warning("Failed to construct LangSmith client", exc_info=True)
        return _NoopTracer()

    return _LangSmithTracer(client, project_name)
