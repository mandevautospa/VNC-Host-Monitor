"""
Alert sender — Phase 4 stub.

SMTP credentials must NEVER be stored in source code or committed to Git.
Load them from environment variables at runtime:

    SMTP_USER      — the SMTP login username
    SMTP_PASSWORD  — the SMTP login password

Set these in Windows via:
    System Properties → Advanced → Environment Variables
or in a .env file (excluded from Git via .gitignore) loaded at startup.

This module is intentionally minimal in Phase 1–3.  Replace the stubs in
send_alert() and send_recovery() once Phase 4 work begins.
"""

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def _smtp_send(subject: str, body: str, config: dict) -> bool:
    alerts_cfg = config.get("alerts", {})

    smtp_host = alerts_cfg.get("smtp_host", "")
    smtp_port = int(alerts_cfg.get("smtp_port", 587))
    smtp_from = alerts_cfg.get("smtp_from", "")
    recipients = alerts_cfg.get("recipients", []) or []
    use_starttls = bool(alerts_cfg.get("smtp_starttls", True))
    timeout_s = float(alerts_cfg.get("smtp_timeout_seconds", 10))

    if not smtp_host or not smtp_from or not recipients:
        logger.error(
            "SMTP config incomplete. Require smtp_host, smtp_from, and recipients."
        )
        return False

    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    if bool(smtp_user) != bool(smtp_password):
        logger.error("SMTP_USER and SMTP_PASSWORD must be set together.")
        return False

    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout_s) as client:
            client.ehlo()
            if use_starttls:
                client.starttls()
                client.ehlo()
            if smtp_user and smtp_password:
                client.login(smtp_user, smtp_password)
            client.send_message(msg)
        return True
    except Exception as exc:
        logger.error("SMTP send failed: %s", exc)
        return False


def send_alert(host: str, status: str, detail: str, config: dict) -> bool:
    """
    Send an alert notification for *host*.

    Args:
        host:   Host name (e.g. "host-03").
        status: Status string (e.g. "P3D_NOT_RUNNING").
        detail: Multi-line human-readable detail block for the message body.
        config: The full central config dict (for SMTP settings / recipients).

    Returns:
        True if the alert was dispatched, False otherwise.
    """
    alerts_cfg = config.get("alerts", {})

    if not alerts_cfg.get("email_enabled", False):
        logger.debug("Email alerts disabled — skipping alert for host=%s status=%s", host, status)
        return False
    subject = f"[P3D Monitor] ALERT {host} {status}"
    return _smtp_send(subject, detail, config)


def send_recovery(host: str, previous_status: str, config: dict) -> bool:
    """
    Send a recovery notification for *host*.

    Args:
        host:            Host name.
        previous_status: The unhealthy status the host recovered from.
        config:          The full central config dict.

    Returns:
        True if the notification was dispatched, False otherwise.
    """
    alerts_cfg = config.get("alerts", {})
    if not alerts_cfg.get("email_enabled", False):
        logger.debug("Email alerts disabled — skipping recovery for host=%s", host)
        return False

    subject = f"[P3D Monitor] RECOVERY {host} HEALTHY"
    body = (
        f"Host: {host}\n"
        f"Recovered From: {previous_status}\n"
        "Current Status: HEALTHY\n"
    )
    return _smtp_send(subject, body, config)
