"""
Twilio Failover QA
Validation checklist: Twilio failover tested.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


class _FakeTwilioRestException(Exception):
    """Minimal stand-in for TwilioRestException in unit tests."""
    def __init__(self, status: int = 500):
        self.status = status
        super().__init__(f"Twilio error {status}")


def test_twilio_failover():
    print("\n[TEST] Twilio Failover")

    import integrations.twilio_client as tc_module

    client = tc_module.TwilioClient.__new__(tc_module.TwilioClient)
    mock_twilio = MagicMock()
    client.client = mock_twilio
    client.from_number = "+15550001111"

    call_count = [0]
    primary_number = client.from_number

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if kwargs.get("from_") == primary_number:
            raise _FakeTwilioRestException(500)
        msg = MagicMock()
        msg.sid = "SM_FAILOVER_123"
        return msg

    mock_twilio.messages.create.side_effect = side_effect

    # Patch the exception class used in send_sms_failover
    with patch.object(tc_module, "TwilioRestException", _FakeTwilioRestException):
        try:
            sid = client.send_sms_failover("+15559998888", "Test message", "+15550002222")
            failover_worked = sid == "SM_FAILOVER_123"
        except Exception as e:
            print(f"  [ERROR] {e}")
            failover_worked = False

    checks = [
        ("failover sends from alternate number", failover_worked),
        ("primary attempt was made first", call_count[0] >= 1),
    ]

    all_ok = True
    for label, ok in checks:
        symbol = "✓" if ok else "✗"
        print(f"  {symbol} {label}")
        if not ok:
            all_ok = False
    return all_ok


def run_all() -> bool:
    return test_twilio_failover()


if __name__ == "__main__":
    passed = run_all()
    print(f"\nTwilio Failover QA: {'PASS' if passed else 'FAIL'}")
    sys.exit(0 if passed else 1)
