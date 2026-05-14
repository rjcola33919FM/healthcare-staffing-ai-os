"""
OpenTelemetry instrumentation — spans, metrics, and trace propagation.
Wraps every agent call and webhook with distributed tracing.
Falls back to structured log output when OTEL collector is not configured.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

OTEL_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
SERVICE_NAME  = os.environ.get("OTEL_SERVICE_NAME", "healthcare-staffing-ai-os")

_tracer = None
_meter  = None


def _get_tracer():
    global _tracer
    if _tracer is not None:
        return _tracer
    if not OTEL_ENDPOINT:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT))
        )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(SERVICE_NAME)
        logger.info("[OTEL] Tracer initialized → %s", OTEL_ENDPOINT)
    except ImportError:
        logger.info("[OTEL] opentelemetry packages not installed — tracing disabled.")
    return _tracer


def _get_meter():
    global _meter
    if _meter is not None:
        return _meter
    if not OTEL_ENDPOINT:
        return None
    try:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=OTEL_ENDPOINT), export_interval_millis=30_000
        )
        provider = MeterProvider(metric_readers=[reader])
        metrics.set_meter_provider(provider)
        _meter = metrics.get_meter(SERVICE_NAME)
    except ImportError:
        pass
    return _meter


@contextmanager
def agent_span(
    agent_id: str,
    operation: str,
    contact_id: str = "",
    **attributes: Any,
) -> Generator[Any, None, None]:
    """
    Context manager that wraps an agent operation in an OTEL span.
    Records duration, agent_id, contact_id, and any extra attributes.
    """
    tracer = _get_tracer()
    start = time.monotonic()

    if tracer:
        with tracer.start_as_current_span(f"{agent_id}.{operation}") as span:
            span.set_attribute("agent.id", agent_id)
            span.set_attribute("agent.operation", operation)
            if contact_id:
                span.set_attribute("contact.id", contact_id)
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
            try:
                yield span
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(
                    __import__("opentelemetry.trace", fromlist=["StatusCode"]).StatusCode.ERROR,
                    str(exc),
                )
                raise
            finally:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                span.set_attribute("duration_ms", elapsed_ms)
    else:
        try:
            yield None
        finally:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.debug(
                "[OTEL] %s.%s contact=%s duration=%dms attrs=%s",
                agent_id, operation, contact_id, elapsed_ms, attributes,
            )


def record_token_usage(
    agent_id: str,
    input_tokens: int,
    output_tokens: int,
    model: str = "claude-opus-4-6",
) -> None:
    """Emit token usage as OTEL counters (or log fallback)."""
    meter = _get_meter()
    if meter:
        counter = meter.create_counter(
            "llm.token.usage",
            description="LLM token usage by agent",
        )
        counter.add(input_tokens,  {"agent_id": agent_id, "model": model, "direction": "input"})
        counter.add(output_tokens, {"agent_id": agent_id, "model": model, "direction": "output"})
    else:
        logger.info(
            "[METRICS] token_usage agent=%s model=%s input=%d output=%d",
            agent_id, model, input_tokens, output_tokens,
        )


def record_escalation(agent_id: str, reason: str, severity: str) -> None:
    """Emit escalation counter metric."""
    meter = _get_meter()
    if meter:
        counter = meter.create_counter(
            "agent.escalation",
            description="Human escalation events by agent",
        )
        counter.add(1, {"agent_id": agent_id, "reason": reason, "severity": severity})
    else:
        logger.warning(
            "[METRICS] escalation agent=%s reason=%s severity=%s",
            agent_id, reason, severity,
        )
