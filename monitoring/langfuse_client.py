"""
Langfuse + OpenTelemetry monitoring for Healthcare Staffing AI OS.
Traces every agent call with agent_id, contact_id, action, and token usage.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

_langfuse_client = None


def _get_client():
    global _langfuse_client
    if _langfuse_client is None and LANGFUSE_SECRET_KEY:
        try:
            from langfuse import Langfuse
            _langfuse_client = Langfuse(
                secret_key=LANGFUSE_SECRET_KEY,
                public_key=LANGFUSE_PUBLIC_KEY,
                host=LANGFUSE_HOST,
            )
        except ImportError:
            logger.warning("[LANGFUSE] langfuse package not installed — tracing disabled.")
    return _langfuse_client


@contextmanager
def trace_event(name: str, **metadata: Any):
    """
    Context manager that wraps a block in a Langfuse trace.
    Falls back to no-op logging if Langfuse is not configured.
    """
    client = _get_client()
    if client:
        trace = client.trace(name=name, metadata=metadata)
        try:
            yield trace
        except Exception as e:
            trace.update(metadata={**metadata, "error": str(e)})
            raise
        finally:
            client.flush()
    else:
        logger.debug("[TRACE] %s %s", name, metadata)
        yield None


def log_agent_call(
    agent_id: str,
    contact_id: str,
    action: str,
    input_tokens: int,
    output_tokens: int,
    escalated: bool = False,
) -> None:
    """Log agent LLM call metrics to Langfuse."""
    client = _get_client()
    if client:
        client.generation(
            name=f"{agent_id}_call",
            model="claude-opus-4-6",
            usage={"input": input_tokens, "output": output_tokens},
            metadata={
                "agent_id": agent_id,
                "contact_id": contact_id,
                "action": action,
                "escalated": escalated,
            },
        )
    else:
        logger.info(
            "[METRICS] agent=%s contact=%s action=%s tokens_in=%d tokens_out=%d escalated=%s",
            agent_id, contact_id, action, input_tokens, output_tokens, escalated,
        )
