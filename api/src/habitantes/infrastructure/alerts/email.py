"""SMTP alert sender — best-effort I/O, never raises.

`send_alert` returns a bool so the watchdog can record `email_sent` without a
broken mail relay ever blocking the safety action (disabling the switch). All
SMTP/connection/auth failures are caught and logged, never propagated.
"""

import logging
import smtplib
from email.message import EmailMessage

from habitantes.config import load_settings

logger = logging.getLogger(__name__)


def send_alert(subject: str, body: str) -> bool:
    """Send a plaintext alert email via SMTP; return True on success, False otherwise.

    Reads recipient and SMTP connection details from `settings.alerts`. Returns
    False (without raising) if the config is incomplete or the send fails.
    """
    alerts = load_settings().alerts

    if not alerts.email_to or not alerts.smtp_host:
        logger.warning("send_alert skipped: email_to or smtp_host not configured")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = alerts.smtp_from
    message["To"] = alerts.email_to
    message.set_content(body)

    try:
        with smtplib.SMTP(alerts.smtp_host, alerts.smtp_port, timeout=10) as server:
            server.starttls()
            if alerts.smtp_user and alerts.smtp_password:
                server.login(alerts.smtp_user, alerts.smtp_password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("send_alert failed: %s", exc)
        return False

    logger.info("Alert email sent to %s", alerts.email_to)
    return True
