"""Phase 108: fictional demo mail is handled before transport and monitoring."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

import email_service
import models
import ops_monitoring as monitor
from digest_scheduler import aggregate_for_user, render_and_send_digest


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["resend", "smtp", "console"])
@pytest.mark.parametrize("recipient", [
    "hoa_helen@demo.example", " HOA_HELEN@DEMO.EXAMPLE ",
    '"Helen Example" <hoa_helen@demo.example>',
    " Helen <hoa_helen@DeMo.ExAmPlE.> ",
])
async def test_demo_suppressed_before_all_transports_and_metrics(
    monkeypatch, caplog, capsys, provider, recipient,
):
    monkeypatch.setattr(email_service.settings, "resend_api_key", "test" if provider == "resend" else "")
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.test" if provider == "smtp" else "")
    resend = AsyncMock(side_effect=AssertionError("Resend must not be called"))
    smtp = AsyncMock(side_effect=AssertionError("SMTP must not be called"))
    metric = Mock(side_effect=AssertionError("No delivery outcome exists"))
    monkeypatch.setattr(email_service, "_send_via_resend", resend)
    monkeypatch.setattr(email_service, "_send_via_smtp", smtp)
    monkeypatch.setattr(monitor, "record_email_result", metric)
    with caplog.at_level("INFO", logger="email_service"):
        assert await email_service.send_email(recipient, "PRIVATE SUBJECT", "PRIVATE BODY") is True
    resend.assert_not_called()
    smtp.assert_not_called()
    metric.assert_not_called()
    assert capsys.readouterr().out == ""
    assert [r.message for r in caplog.records if r.name == "email_service"] == [
        "Email suppressed: fictional demo.example recipient",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient", [
    "demo.example", "@demo.example", "person@example.org", "person@demo.example.com", "person@notdemo.example",
    "person@sub.demo.example", '"demo.example" <person@example.org>',
    '"person@demo.example"@example.org',
])
@pytest.mark.parametrize("provider", ["resend", "smtp"])
@pytest.mark.parametrize("outcome", [True, False])
async def test_real_and_lookalike_recipients_preserve_transport_and_outcome(
    monkeypatch, recipient, provider, outcome,
):
    monkeypatch.setattr(email_service.settings, "resend_api_key", "test" if provider == "resend" else "")
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.test")
    resend, smtp, metric = AsyncMock(return_value=outcome), AsyncMock(return_value=outcome), Mock()
    monkeypatch.setattr(email_service, "_send_via_resend", resend)
    monkeypatch.setattr(email_service, "_send_via_smtp", smtp)
    monkeypatch.setattr(monitor, "record_email_result", metric)
    assert await email_service.send_email(recipient, "subject", "body") is outcome
    (resend if provider == "resend" else smtp).assert_awaited_once_with(recipient, "subject", "body")
    (smtp if provider == "resend" else resend).assert_not_called()
    metric.assert_called_once_with(outcome)


@pytest.mark.asyncio
async def test_real_console_recipient_keeps_existing_behavior(monkeypatch, capsys):
    monkeypatch.setattr(email_service.settings, "resend_api_key", "")
    monkeypatch.setattr(email_service.settings, "smtp_host", "")
    metric = Mock()
    monkeypatch.setattr(monitor, "record_email_result", metric)
    assert await email_service.send_email("real@example.org", "subject", "console-body") is True
    assert capsys.readouterr().out == "console-body\n"
    metric.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_suppression_preserves_real_failure_streak(monkeypatch):
    monitor.reset_runtime_state_for_tests()
    monkeypatch.setattr(email_service.settings, "resend_api_key", "test")
    transport = AsyncMock(return_value=False)
    monkeypatch.setattr(email_service, "_send_via_resend", transport)
    try:
        for _ in range(3):
            assert await email_service.send_email("real@example.org", "subject", "body") is False
        before = monitor._email_component()
        assert before["status"] == "error"
        assert await email_service.send_email("demo@demo.example", "subject", "body") is True
        assert monitor._email_component() == before
        assert transport.await_count == 3
        transport.return_value = True
        assert await email_service.send_email("real@example.org", "subject", "body") is True
        assert monitor._email_component()["status"] == "ok"
    finally:
        monitor.reset_runtime_state_for_tests()


@pytest.mark.asyncio
@pytest.mark.parametrize("cadence", ["daily", "weekly"])
async def test_digest_processes_demo_and_real_members_without_demo_transport(db, monkeypatch, cadence):
    monkeypatch.setattr(email_service.settings, "resend_api_key", "test")
    transport, metric = AsyncMock(return_value=True), Mock()
    monkeypatch.setattr(email_service, "_send_via_resend", transport)
    monkeypatch.setattr(monitor, "record_email_result", metric)
    org = models.Organization(name="Demo", slug="phase108-demo", is_demo=True)
    db.add(org)
    db.flush()
    for username, address in [("fictional", "hoa_helen@demo.example"), ("real", "real@example.org")]:
        user = models.User(username=username, display_name=username, email=address,
                           email_verified=True, password_hash="unused")
        db.add(user)
        db.flush()
        db.add(models.NotificationPreference(user_id=user.id, event_type="comment.replied",
                                            channel=f"email_{cadence}", enabled=True))
        row = models.Notification(user_id=user.id, org_id=org.id, event_type="comment.replied",
                                  payload={"actor_display_name": "Example", "proposal_title": "Demo topic"},
                                  created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.add(row)
        db.flush()
        aggregate = aggregate_for_user(db, user, cadence)
        assert not aggregate.is_empty
        assert await render_and_send_digest(db, aggregate) is True
        db.refresh(row)
        assert row.payload["delivered_in_digest"] is True
        assert aggregate_for_user(db, user, cadence).is_empty
        assert user.email_verified is True
        if username == "fictional":
            transport.assert_not_called()
            metric.assert_not_called()
    transport.assert_awaited_once()
    assert transport.await_args.args[0] == "real@example.org"
    metric.assert_called_once_with(True)
