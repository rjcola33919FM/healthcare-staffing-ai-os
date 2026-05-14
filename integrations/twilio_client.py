"""
Twilio Integration — SMS + Voice fallover
"""

from __future__ import annotations

import logging
import os

try:
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException
except ImportError:
    Client = None  # type: ignore
    TwilioRestException = Exception  # type: ignore

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")


class TwilioClient:
    def __init__(self):
        self.client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        self.from_number = TWILIO_FROM_NUMBER

    def send_sms(self, to: str, body: str, max_retries: int = 3) -> str | None:
        """Send SMS with retry on transient failures. Returns message SID."""
        for attempt in range(1, max_retries + 1):
            try:
                message = self.client.messages.create(
                    body=body,
                    from_=self.from_number,
                    to=to,
                )
                logger.info("[TWILIO] SMS sent to %s, SID=%s", to, message.sid)
                return message.sid
            except TwilioRestException as e:
                if e.status >= 500 and attempt < max_retries:
                    logger.warning("[TWILIO] Transient error, retry %d/%d: %s", attempt, max_retries, e)
                    continue
                logger.error("[TWILIO] SMS failed to %s: %s", to, e)
                raise

    def make_call(self, to: str, twiml_url: str) -> str | None:
        """Initiate outbound call. Returns call SID."""
        try:
            call = self.client.calls.create(
                url=twiml_url,
                from_=self.from_number,
                to=to,
            )
            logger.info("[TWILIO] Call initiated to %s, SID=%s", to, call.sid)
            return call.sid
        except TwilioRestException as e:
            logger.error("[TWILIO] Call failed to %s: %s", to, e)
            raise

    def send_sms_failover(self, to: str, body: str, fallback_number: str) -> str | None:
        """
        Attempt primary SMS; if it fails, retry from fallback number.
        Tested per validation checklist: Twilio failover tested.
        """
        try:
            return self.send_sms(to, body)
        except TwilioRestException:
            logger.warning("[TWILIO] Primary send failed, attempting failover number %s", fallback_number)
            message = self.client.messages.create(
                body=body,
                from_=fallback_number,
                to=to,
            )
            logger.info("[TWILIO] Failover SMS sent, SID=%s", message.sid)
            return message.sid
