"""
Domain exceptions for Healthcare Staffing AI OS.
"""


class HealthcareStaffingError(Exception):
    """Base exception for all domain errors."""


class HIPAAGuardrailError(HealthcareStaffingError):
    """Raised when a response triggers a HIPAA or regulated-decision guardrail."""
    def __init__(self, agent_id: str, trigger: str):
        self.agent_id = agent_id
        self.trigger = trigger
        super().__init__(f"[{agent_id}] HIPAA guardrail triggered: '{trigger}'")


class EscalationRequired(HealthcareStaffingError):
    """Raised when an event must be routed to a human immediately."""
    def __init__(self, reason: str, contact_id: str = ""):
        self.reason = reason
        self.contact_id = contact_id
        super().__init__(f"Human escalation required: {reason}")


class AgentRoutingError(HealthcareStaffingError):
    """Raised when the orchestrator cannot determine a valid routing target."""
    def __init__(self, event_type: str):
        self.event_type = event_type
        super().__init__(f"No valid routing target for event_type='{event_type}'")


class CRMSyncError(HealthcareStaffingError):
    """Raised when a GoHighLevel CRM write or sync operation fails."""
    def __init__(self, operation: str, contact_id: str, detail: str = ""):
        self.operation = operation
        self.contact_id = contact_id
        super().__init__(f"CRM sync failed: op={operation} contact={contact_id} — {detail}")


class CredentialValidationError(HealthcareStaffingError):
    """Raised when a credential document fails classification (not approval)."""
    def __init__(self, credential_type: str, reason: str):
        self.credential_type = credential_type
        self.reason = reason
        super().__init__(f"Credential validation error: type={credential_type} — {reason}")


class PHIExposureError(HealthcareStaffingError):
    """Raised when PHI is detected outside a HIPAA-compliant context."""
    def __init__(self, context: str):
        super().__init__(f"PHI exposure detected in: {context}")


class AgentLoadError(HealthcareStaffingError):
    """Raised when an agent fails to load its manifest, prompt, or fusion config."""
    def __init__(self, agent_id: str, missing: str):
        super().__init__(f"Agent {agent_id} failed to load: {missing}")
