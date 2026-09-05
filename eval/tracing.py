"""LangSmith tracer that is enabled only when tracing is explicitly opted-in.

Behavior:
- If `LANGCHAIN_TRACING_V2` is not set to a truthy value, returns a no-op tracer.
- If the LangSmith SDK or API key is missing, returns a no-op tracer.
- Otherwise constructs a thin tracer that forwards `record(event, payload)` to the
  LangSmith client using a few common call shapes.

This keeps imports safe and ensures tracing is opt-in via env.
"""
from typing import Any, Dict, Optional
import os
import langsmith

class _NoopTracer:
    enabled = False

    def record(self, event: str, payload: Dict[str, Any]) -> Optional[Any]:
        return None


class _Tracer:
    def __init__(self, client: Any):
        self.client = client
        self.enabled = True

    def record(self, event: str, payload: Dict[str, Any]) -> Optional[Any]:
        created = None
        try:
            if hasattr(self.client, "create_trace"):
                created = self.client.create_trace(name=event, data=payload)
            elif hasattr(self.client, "log"):
                created = self.client.log(event, payload)
            elif hasattr(self.client, "create_run"):
                try:
                    created = self.client.create_run(name=event, inputs=payload, run_type="tool")
                except Exception:
                    try:
                        created = self.client.create_run(event, payload, "tool")
                    except Exception:
                        created = None
            elif hasattr(self.client, "create"):
                try:
                    created = self.client.create(name=event, data=payload)
                except Exception:
                    created = None
        except Exception:
            created = None

        return created


def _is_truthy(value: Optional[str]) -> bool:
    if not value:
        return False
    return True


def get_tracer():
    # Opt-in check: require LANGCHAIN_TRACING_V2 to be truthy
    if not _is_truthy(os.environ.get("LANGCHAIN_TRACING_V2", "")):
        return _NoopTracer()

    # LangSmith SDK required
    if langsmith is None:
        return _NoopTracer()

    key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    if not key:
        return _NoopTracer()

    Client = getattr(langsmith, "Client", None)
    if Client is None:
        return _NoopTracer()

    # Try common constructor patterns
    client = None
    try:
        try:
            client = Client(api_key=key)
        except Exception:
            client = Client(key)
    except Exception:
        client = None

    if client is None:
        return _NoopTracer()

    return _Tracer(client)
