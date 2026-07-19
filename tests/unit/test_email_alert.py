"""Unit tests for T7 — SMTP alert sender (infrastructure/alerts/email.py).

send_alert builds a well-formed message and sends it over a (mocked) SMTP
connection, and returns False without raising when the connection fails or the
config is incomplete — a broken mail relay must never block the safety action.
"""

import smtplib
from types import SimpleNamespace
from unittest.mock import MagicMock

from habitantes.infrastructure.alerts import email as email_module


def _alerts(**overrides):
    base = {
        "email_to": "ops@example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "user",
        "smtp_password": "secret",
        "smtp_from": "control-center@habitantes-grenoble.app",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_settings(monkeypatch, alerts):
    monkeypatch.setattr(
        email_module, "load_settings", lambda: SimpleNamespace(alerts=alerts)
    )


def test_send_alert_sends_well_formed_message(monkeypatch):
    _patch_settings(monkeypatch, _alerts())

    server = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = server
    smtp_ctor = MagicMock(return_value=smtp_cm)
    monkeypatch.setattr(smtplib, "SMTP", smtp_ctor)

    result = email_module.send_alert("Bot disabled", "Daily cost limit breached")

    assert result is True
    smtp_ctor.assert_called_once_with("smtp.example.com", 587, timeout=10)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("user", "secret")
    server.send_message.assert_called_once()

    sent = server.send_message.call_args.args[0]
    assert sent["Subject"] == "Bot disabled"
    assert sent["To"] == "ops@example.com"
    assert sent["From"] == "control-center@habitantes-grenoble.app"
    assert "Daily cost limit breached" in sent.get_content()


def test_send_alert_uses_smtp_ssl_on_port_465(monkeypatch):
    _patch_settings(monkeypatch, _alerts(smtp_port=465, smtp_host="smtp.ionos.fr"))

    server = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = server
    ssl_ctor = MagicMock(return_value=smtp_cm)
    starttls_ctor = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP_SSL", ssl_ctor)
    monkeypatch.setattr(smtplib, "SMTP", starttls_ctor)

    result = email_module.send_alert("Bot disabled", "Daily cost limit breached")

    assert result is True
    ssl_ctor.assert_called_once_with("smtp.ionos.fr", 465, timeout=10)
    starttls_ctor.assert_not_called()
    server.login.assert_called_once_with("user", "secret")
    server.send_message.assert_called_once()


def test_send_alert_returns_false_on_connection_error(monkeypatch):
    _patch_settings(monkeypatch, _alerts())

    def _boom(*args, **kwargs):
        raise smtplib.SMTPConnectError(421, "cannot connect")

    monkeypatch.setattr(smtplib, "SMTP", _boom)

    result = email_module.send_alert("subj", "body")

    assert result is False


def test_send_alert_returns_false_on_os_error(monkeypatch):
    _patch_settings(monkeypatch, _alerts())

    def _boom(*args, **kwargs):
        raise OSError("network unreachable")

    monkeypatch.setattr(smtplib, "SMTP", _boom)

    assert email_module.send_alert("subj", "body") is False


def test_send_alert_skips_when_unconfigured(monkeypatch):
    _patch_settings(monkeypatch, _alerts(email_to="", smtp_host=""))

    smtp_ctor = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP", smtp_ctor)

    result = email_module.send_alert("subj", "body")

    assert result is False
    smtp_ctor.assert_not_called()
