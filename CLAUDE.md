# Healthcare Staffing AI OS — CLAUDE.md

## Project Identity
**Name:** Healthcare Staffing AI OS
**Industry:** Healthcare staffing, medical recruiting, credentialing, compliance, client sales
**Architecture:** Master orchestrator + 5 specialized agents, HIPAA-aware, GoHighLevel-native

---

## Agent Registry

| Agent ID   | Name                                  | Role                                      |
|------------|---------------------------------------|-------------------------------------------|
| ORCH-001   | Healthcare Staffing Orchestrator Agent| Master router, CRM state, escalation mgr |
| REC-001    | Candidate Recruiting Agent            | Intake, FAQ, appointment booking          |
| CRED-001   | Medical Credentialing Agent           | Document collection, checklist, reminders |
| COMP-001   | Compliance Monitoring Agent           | Expiry monitoring, alerts, audit trail    |
| SALES-001  | Client Sales Qualification Agent      | Lead qualification, sales appointments    |
| CRM-001    | CRM Operations Agent                  | Tags, pipeline, notes, tasks, webhooks    |

---

## Model Settings (All Agents)
- **Model:** `claude-opus-4-6` (production) / `claude-sonnet-4-6` (dev/test)
- **Temperature:** 0.05
- **Top P:** 0.1
- **Frequency Penalty:** 0
- **Presence Penalty:** 0
- **Reasoning:** High (deterministic, rule-based)

---

## Tech Stack

| Layer      | Technology               |
|------------|--------------------------|
| LLM        | Claude Opus 4.6 / Sonnet |
| CRM        | GoHighLevel              |
| Voice      | Twilio + VAPI            |
| SMS        | Twilio                   |
| Backend    | Python + FastAPI         |
| Queue      | Redis                    |
| DB         | PostgreSQL               |
| Vector DB  | Pinecone                 |
| Auth       | Auth0                    |
| Infra      | Docker + AWS             |
| Monitoring | Langfuse + OpenTelemetry |

---

## Repository Structure

```
healthcare-staffing-ai-os/
├── agents/              # Per-agent persona.json (model settings)
├── manifests/           # Agent manifest JSON (id, role, guardrails, tools)
├── prompts/             # System prompts (.txt) per agent
├── fusion/              # Fusion profile JSON per agent
├── orchestration/       # Router logic (router.py)
├── src/
│   ├── main.py          # FastAPI webhooks (GHL, Twilio, VAPI)
│   ├── agents/          # Agent classes (base + 6 specialized)
│   ├── queue/           # Redis async queue
│   └── models/          # Pydantic schemas
├── integrations/        # GHL, Twilio, VAPI clients
├── monitoring/          # Langfuse + OpenTelemetry
├── qa/                  # QA scripts and test suite
├── infrastructure/      # Dockerfile, docker-compose
├── compliance/          # HIPAA compliance notes
├── memory/              # Agent memory / RAG context store
├── rag/                 # RAG pipeline
├── kb/                  # Knowledge base documents
├── workflows/           # GHL workflow definitions
└── .env.example
```

---

## HIPAA & Compliance Rules (NON-NEGOTIABLE)

1. **No clinical, legal, or credentialing approval decisions** without human review.
2. **No PHI** in CRM notes — reference document IDs only.
3. **All agent actions** must be audit-logged with timestamp, agent_id, contact_id.
4. **Audit log is append-only** — never delete entries.
5. **PHI exposure** triggers immediate COMP-001 escalation.
6. **Human escalation tag** `human_escalation_required` must be applied before any human queue routing.

---

## Escalation Rules

| Trigger                            | Route To   |
|------------------------------------|------------|
| Credential approval decision       | HUMAN      |
| Contract terms / pricing exception | HUMAN      |
| Candidate rejection / disqualification | HUMAN  |
| Adverse compliance flag            | HUMAN      |
| PHI exposure event                 | HUMAN      |
| Ambiguous CRM merge conflict       | HUMAN      |

---

## Sprint Methodology

| Sprint | Scope |
|--------|-------|
| Sprint 0 | Repository scaffold, agent definitions, orchestrator, FastAPI skeleton, QA scripts, Docker |
| Sprint 1 | GHL workflow integration, pipeline stage automation, SMS/voice flows |
| Sprint 2 | RAG/KB ingestion, vector DB setup, context injection |
| Sprint 3 | Compliance dashboard, expiry monitoring automation, audit reports |
| Sprint 4 | Auth0 integration, production hardening, load testing |

---

## Validation Checklist

- [x] Agent QA PASS (run: `python qa/run_all_qa.py`)
- [x] Orchestration QA PASS
- [x] Credentialing workflows tested
- [x] HIPAA boundaries validated
- [x] Audit logging enabled
- [x] Retry logic tested
- [x] Human escalation tested
- [x] CRM sync validated
- [x] Twilio failover tested

---

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run QA suite
python qa/run_all_qa.py

# Start API (development)
uvicorn src.main:app --reload --port 8000

# Start with Docker
cd infrastructure && docker-compose up --build

# Validate agent manifests only
python qa/validate_agents.py
```

---

## Architecture Constraints

- Do NOT redesign agent architecture without explicit instruction.
- Preserve all manifest IDs, persona settings, and fusion weights exactly as defined.
- All new agents must pass `qa/validate_agents.py` before merge.
- All escalation paths must route through `orchestration/router.py`.
- Temperature must remain ≤ 0.1 for all production agents.
