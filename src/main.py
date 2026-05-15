"""
Healthcare Staffing AI OS — FastAPI Application
Webhook entrypoint for GoHighLevel, Twilio, and VAPI events.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import anthropic
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.agents.base import AgentContext
from src.agents.orchestrator import OrchestratorAgent
from src.agents.recruiting import RecruitingAgent
from src.agents.credentialing import CredentialingAgent
from src.agents.compliance import ComplianceAgent
from src.agents.sales import SalesAgent
from src.agents.crm import CRMAgent
from src.queue.redis_queue import enqueue_event, get_queue
from src.monitoring.langfuse_client import trace_event
from rag import RAGPipeline
from memory import MemoryManager
from context import ContextInjector
from audit_log import configure_logging, get_audit_logger
from monitoring import MetricsCollector, agent_span
from compliance import HIPAAGuard, ComplianceReporter
from security import require_auth, ip_rate_limit
from db import create_all, dispose
from workflows import WorkflowExecutor, WorkflowEvent, ExpiryScheduler

configure_logging()
logger = logging.getLogger(__name__)

_audit = get_audit_logger()
_metrics = MetricsCollector.get()

# Agent registry — initialized at startup
_agents: dict[str, Any] = {}
_orchestrator: OrchestratorAgent | None = None
_context_injector: ContextInjector | None = None
_workflow_executor: WorkflowExecutor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agents, _orchestrator, _context_injector, _workflow_executor
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("[STARTUP] ANTHROPIC_API_KEY not set — agents will not function.")
    client = anthropic.Anthropic(api_key=api_key or "placeholder")
    _orchestrator = OrchestratorAgent(client)
    _agents = {
        "REC-001": RecruitingAgent(client),
        "CRED-001": CredentialingAgent(client),
        "COMP-001": ComplianceAgent(client),
        "SALES-001": SalesAgent(client),
        "CRM-001": CRMAgent(client),
    }

    # RAG + memory + context assembly
    rag = RAGPipeline(anthropic_client=client)
    rag.build_index()
    memory = MemoryManager(anthropic_client=client)
    _context_injector = ContextInjector(rag_pipeline=rag, memory_manager=memory)

    # Workflow executor
    _workflow_executor = WorkflowExecutor()

    # Database schema sync
    try:
        await create_all()
    except Exception as exc:
        logger.warning("[DB] Schema sync skipped (no DB connection): %s", exc)

    _audit.log_agent_action("SYSTEM", "", "startup", "All agents initialized")
    logger.info("Healthcare Staffing AI OS — all agents initialized.")
    yield
    await dispose()
    _audit.log_agent_action("SYSTEM", "", "shutdown", "Application shutting down")
    logger.info("Healthcare Staffing AI OS — shutting down.")


app = FastAPI(
    title="Healthcare Staffing AI OS",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ── Request Schemas ────────────────────────────────────────────────────────────

class WebhookPayload(BaseModel):
    contact_id: str
    conversation_id: str
    channel: str = "webhook"
    event_type: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = {}


class TwilioSMSPayload(BaseModel):
    From: str
    To: str
    Body: str
    MessageSid: str


class VAPIVoicePayload(BaseModel):
    call_id: str
    contact_id: str
    transcript: str
    event_type: str = "candidate_message"


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "Healthcare Staffing AI OS",
        "version": "1.0.0",
        "status": "online",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agents": list(_agents.keys()),
        "rag_ready": _context_injector is not None and _context_injector.rag is not None,
        "memory_ready": _context_injector is not None and _context_injector.memory is not None,
    }


# ── GoHighLevel Webhook ────────────────────────────────────────────────────────

@app.post("/webhook/ghl", dependencies=[Depends(ip_rate_limit())])
async def ghl_webhook(payload: WebhookPayload):
    """Inbound GoHighLevel CRM webhook — route to appropriate agent."""
    import time
    start = time.monotonic()

    context = AgentContext(
        contact_id=payload.contact_id,
        conversation_id=payload.conversation_id,
        channel=payload.channel,
        payload=payload.model_dump(),
    )

    with trace_event("ghl_webhook", contact_id=payload.contact_id):
        with agent_span("ORCH-001", "dispatch", contact_id=payload.contact_id):
            response = _orchestrator.dispatch(context, _agents)

    # HIPAA: scan response content before any outbound action
    phi_hits = HIPAAGuard.check_text(
        response.content or "", agent_id=response.agent_id, contact_id=payload.contact_id
    )
    if phi_hits:
        _audit.log_phi_event(
            response.agent_id, payload.contact_id,
            phi_pattern=str(phi_hits), source="ghl_response", action_taken="flagged",
        )

    _audit.log_agent_action(
        response.agent_id, payload.contact_id, response.action,
        detail=f"escalation={response.escalation_reason or 'none'}",
        session_id=payload.conversation_id,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    _metrics.record_call(
        response.agent_id,
        duration_ms=elapsed_ms,
        escalated=bool(response.escalation_reason),
    )

    await enqueue_event("crm_sync", {
        "contact_id": payload.contact_id,
        "agent_id": response.agent_id,
        "action": response.action,
        "crm_updates": response.crm_updates,
    })

    return {
        "agent_id": response.agent_id,
        "action": response.action,
        "content": response.content,
        "escalation_reason": response.escalation_reason,
    }


# ── Twilio SMS Webhook ─────────────────────────────────────────────────────────

@app.post("/webhook/twilio/sms")
async def twilio_sms(payload: TwilioSMSPayload):
    """Inbound SMS from Twilio — classify and route."""
    context = AgentContext(
        contact_id=payload.From,
        conversation_id=payload.MessageSid,
        channel="sms",
        payload={
            "message": payload.Body,
            "from": payload.From,
            "to": payload.To,
        },
    )

    with trace_event("twilio_sms", contact_id=payload.From):
        response = _orchestrator.dispatch(context, _agents)

    return {"status": "accepted", "action": response.action}


# ── VAPI Voice Webhook ─────────────────────────────────────────────────────────

@app.post("/webhook/vapi/voice")
async def vapi_voice(payload: VAPIVoicePayload):
    """Inbound VAPI voice transcript — route to agent."""
    context = AgentContext(
        contact_id=payload.contact_id,
        conversation_id=payload.call_id,
        channel="voice",
        payload={
            "message": payload.transcript,
            "event_type": payload.event_type,
        },
    )

    with trace_event("vapi_voice", contact_id=payload.contact_id):
        response = _orchestrator.dispatch(context, _agents)

    return {"agent_id": response.agent_id, "action": response.action}


# ── Metrics ───────────────────────────────────────────────────────────────────

@app.get("/metrics", dependencies=[Depends(require_auth)])
async def metrics():
    """Live agent performance metrics snapshot (authenticated)."""
    return _metrics.snapshot()


# ── Compliance Reports ─────────────────────────────────────────────────────────

@app.get("/compliance/report/daily", dependencies=[Depends(require_auth)])
async def compliance_daily(date: str | None = None):
    """Daily audit summary. date format: YYYYMMDD. Defaults to today."""
    reporter = ComplianceReporter(_audit)
    return reporter.daily_summary(date)


@app.get("/compliance/report/phi", dependencies=[Depends(require_auth)])
async def compliance_phi(days: int = 30):
    """PHI detection events over the last N days."""
    reporter = ComplianceReporter(_audit)
    return reporter.phi_event_report(days=days)


@app.get("/compliance/report/escalations", dependencies=[Depends(require_auth)])
async def compliance_escalations(days: int = 7):
    """Human escalation events over the last N days."""
    reporter = ComplianceReporter(_audit)
    return reporter.escalation_report(days=days)


# ── Workflow: GHL Stage Change ────────────────────────────────────────────────

class StageChangePayload(BaseModel):
    contact_id: str
    from_stage: str
    candidate_data: dict[str, Any] = {}
    session_id: str = ""


@app.post("/webhook/ghl/stage-changed", dependencies=[Depends(ip_rate_limit())])
async def ghl_stage_changed(payload: StageChangePayload):
    """GHL pipeline stage-change webhook — drives workflow automation."""
    event = WorkflowEvent(
        event_type="contact.stage_changed",
        contact_id=payload.contact_id,
        session_id=payload.session_id,
        data={
            "from_stage": payload.from_stage,
            "candidate_data": payload.candidate_data,
        },
    )
    result = _workflow_executor.run(event)
    _audit.log_agent_action(
        "ORCH-001", payload.contact_id, "stage_changed",
        detail=f"from={payload.from_stage} actions={result.actions_taken}",
        session_id=payload.session_id,
    )
    return {
        "success": result.success,
        "actions_taken": result.actions_taken,
        "crm_updates": result.crm_updates,
        "escalation": result.escalation,
        "error": result.error or None,
    }


# ── Internal: Expiry Check (cron) ─────────────────────────────────────────────

@app.post("/internal/expiry-check", dependencies=[Depends(require_auth)])
async def expiry_check():
    """
    Credential expiry sweep — triggered daily by EventBridge / external cron.
    Fires 30/14/7-day reminders for all candidates with expiring documents.
    """
    scheduler = ExpiryScheduler(executor=_workflow_executor)
    summary = await scheduler.run_daily_sweep()
    _audit.log_agent_action("COMP-001", "", "expiry_sweep", detail=str(summary))
    return summary


# ── Queue Worker Trigger ───────────────────────────────────────────────────────

@app.post("/internal/process-queue")
async def process_queue():
    """Drain one item from the Redis event queue (called by worker)."""
    queue = await get_queue()
    event = await queue.dequeue()
    if not event:
        return {"status": "empty"}
    logger.info("[QUEUE] Processing event: %s", event)
    return {"status": "processed", "event": event}
