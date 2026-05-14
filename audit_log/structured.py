"""
Structured JSON logging — configures the root logger to emit JSON lines
for ingestion by CloudWatch, Datadog, or any log aggregator.

Call configure_logging() once at application startup (src/main.py).
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any


SERVICE_NAME = os.environ.get("SERVICE_NAME", "healthcare-staffing-ai-os")
LOG_LEVEL    = os.environ.get("LOG_LEVEL", "INFO").upper()


class JSONFormatter(logging.Formatter):
    """
    Emits each log record as a single JSON line.
    Fields: timestamp, level, service, logger, message, [exc_info].
    Extra fields passed via logger.info(..., extra={...}) are included.
    """

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":     record.levelname,
            "service":   SERVICE_NAME,
            "logger":    record.name,
            "message":   record.getMessage(),
        }

        # Include extra fields (e.g. agent_id, contact_id passed via extra={})
        for key, value in record.__dict__.items():
            if key not in _STDLIB_LOG_ATTRS and not key.startswith("_"):
                data[key] = value

        if record.exc_info:
            data["exc_info"] = traceback.format_exception(*record.exc_info)

        return json.dumps(data, default=str, separators=(",", ":"))


# Python stdlib LogRecord attributes we don't re-emit
_STDLIB_LOG_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


def configure_logging(level: str = LOG_LEVEL, json_output: bool | None = None) -> None:
    """
    Configure root logger.
    json_output defaults to True in production, False in development
    (plain text is easier to read locally).
    """
    app_env = os.environ.get("APP_ENV", "development")
    if json_output is None:
        json_output = app_env == "production"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))

    # Remove any existing handlers (e.g. from basicConfig)
    root.handlers.clear()

    handler = logging.StreamHandler()
    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
        )

    root.addHandler(handler)
    logging.getLogger(__name__).info(
        "[LOG] Logging configured level=%s json=%s", level, json_output
    )


class AgentLogAdapter(logging.LoggerAdapter):
    """
    Adapter that automatically injects agent_id and contact_id into every
    log record emitted by an agent, without requiring callers to pass extra={}.

    Usage:
        log = AgentLogAdapter.for_agent("REC-001", "c-123")
        log.info("Sent credentialing link")
        # → {"message": "Sent credentialing link", "agent_id": "REC-001", ...}
    """

    @classmethod
    def for_agent(cls, agent_id: str, contact_id: str = "") -> "AgentLogAdapter":
        base_logger = logging.getLogger(f"agent.{agent_id}")
        return cls(base_logger, {"agent_id": agent_id, "contact_id": contact_id})

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs
