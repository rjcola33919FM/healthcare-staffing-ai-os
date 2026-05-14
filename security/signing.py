"""
Webhook Request Signing — validates inbound webhook signatures from GHL and Twilio.
Prevents replay attacks and spoofed webhook calls.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

GHL_WEBHOOK_SECRET   = os.environ.get("GHL_WEBHOOK_SECRET", "")
TWILIO_AUTH_TOKEN    = os.environ.get("TWILIO_AUTH_TOKEN", "")
REPLAY_WINDOW_SECS   = 300   # reject webhooks older than 5 minutes


# ── GoHighLevel Signature Validation ──────────────────────────────────────────

def verify_ghl_signature(
    payload_bytes: bytes,
    signature_header: str,
    secret: str = GHL_WEBHOOK_SECRET,
) -> bool:
    """
    GHL signs webhooks with HMAC-SHA256.
    Header format: X-GHL-Signature: sha256=<hex_digest>
    """
    if not secret:
        logger.warning("[SIGN] GHL_WEBHOOK_SECRET not set — signature check skipped.")
        return True  # dev mode: allow

    if not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    provided = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided)


# ── Twilio Signature Validation ────────────────────────────────────────────────

def verify_twilio_signature(
    url: str,
    params: dict[str, str],
    signature: str,
    auth_token: str = TWILIO_AUTH_TOKEN,
) -> bool:
    """
    Validates a Twilio webhook signature per Twilio's algorithm:
    HMAC-SHA1(auth_token, url + sorted_params)
    """
    if not auth_token:
        logger.warning("[SIGN] TWILIO_AUTH_TOKEN not set — signature check skipped.")
        return True

    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(auth_token)
        return validator.validate(url, params, signature)
    except ImportError:
        # Manual fallback if twilio SDK not available
        s = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
        digest = hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()
        import base64
        expected = base64.b64encode(digest).decode()
        return hmac.compare_digest(expected, signature)


# ── Timestamp-based Replay Protection ─────────────────────────────────────────

def check_timestamp(ts_header: str, window: int = REPLAY_WINDOW_SECS) -> None:
    """
    Raises HTTPException if the timestamp in the header is outside the replay window.
    Supports Unix epoch (int string) and ISO-8601 formats.
    """
    if not ts_header:
        return   # no timestamp provided — skip check
    try:
        ts = int(ts_header)
    except ValueError:
        from datetime import datetime, timezone
        try:
            ts = int(datetime.fromisoformat(ts_header).timestamp())
        except Exception:
            logger.warning("[SIGN] Unparseable timestamp header: %s", ts_header)
            return
    age = time.time() - ts
    if age > window:
        logger.warning("[SIGN] Replay attack: timestamp age=%ds > window=%ds", age, window)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook timestamp outside replay window.",
        )


# ── FastAPI dependency helpers ─────────────────────────────────────────────────

async def validate_ghl_webhook(request: Request) -> bytes:
    """
    FastAPI dependency for GHL webhooks.
    Reads raw body, validates signature, returns body for further parsing.
    """
    body = await request.body()
    sig  = request.headers.get("X-GHL-Signature", "")
    ts   = request.headers.get("X-GHL-Timestamp", "")

    check_timestamp(ts)

    if GHL_WEBHOOK_SECRET and not verify_ghl_signature(body, sig):
        logger.warning("[SIGN] GHL signature mismatch — request rejected.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid GHL signature.")

    return body


async def validate_twilio_webhook(request: Request) -> dict[str, str]:
    """
    FastAPI dependency for Twilio SMS webhooks.
    Validates Twilio signature and returns form-decoded params.
    """
    form = await request.form()
    params = dict(form)
    sig = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)

    if TWILIO_AUTH_TOKEN and not verify_twilio_signature(url, params, sig):
        logger.warning("[SIGN] Twilio signature mismatch — request rejected.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Twilio signature.")

    return params
