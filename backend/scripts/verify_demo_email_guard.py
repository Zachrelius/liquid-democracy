"""Safely prove the deployed demo-email guard without sends or database writes.

Run from the deployed backend: python scripts/verify_demo_email_guard.py
Both transports are replaced with tripwires before exercising the real sender.
"""
import asyncio
from contextlib import redirect_stdout
import io
import logging
from pathlib import Path
import sys
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import email_service
import ops_monitoring


async def verify():
    output = io.StringIO()
    logs = io.StringIO()
    handler = logging.StreamHandler(logs)
    old_level = email_service.log.level
    resend = AsyncMock(side_effect=AssertionError("Resend transport reached"))
    smtp = AsyncMock(side_effect=AssertionError("SMTP transport reached"))
    metric = Mock(side_effect=AssertionError("Delivery monitoring reached"))
    email_service.log.addHandler(handler)
    email_service.log.setLevel(logging.INFO)
    try:
        with patch.object(email_service, "_send_via_resend", resend), \
             patch.object(email_service, "_send_via_smtp", smtp), \
             patch.object(ops_monitoring, "record_email_result", metric), \
             redirect_stdout(output):
            handled = await email_service.send_email(
                "Phase 108 probe <guard_probe@DeMo.ExAmPlE.>",
                "Synthetic guard probe", "Synthetic guard probe body",
            )
        assert handled is True, "Suppression was not handled"
        resend.assert_not_called()
        smtp.assert_not_called()
        metric.assert_not_called()
        assert output.getvalue() == "", "Console body output occurred"
        assert logs.getvalue().strip() == "Email suppressed: fictional demo.example recipient"
    finally:
        email_service.log.removeHandler(handler)
        email_service.log.setLevel(old_level)
        handler.close()
    print("PASS: demo recipient handled; transports=0; delivery metrics=0; console body=0; suppression log verified")


if __name__ == "__main__":
    asyncio.run(verify())
