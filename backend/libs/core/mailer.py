"""Transactional email over SMTP, with credentials in SSM:

    /cdts/<stage>/smtp/user      -> sender address (String)
    /cdts/<stage>/smtp/password  -> app password (SecureString)

`send_email` never raises: a mailbox that cannot be reached must not roll back
the database work that triggered the notification. Callers get a bool and
decide whether to surface an alternative channel.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

import boto3

from libs.core.logger import Logger

STAGE = os.environ.get("STAGE", "dev")
SSM_SMTP_PATH = os.environ.get("SSM_SMTP_PATH", f"/cdts/{STAGE}/smtp")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))

_creds: tuple[str, str] | None = None
_creds_loaded = False


def _load_creds() -> tuple[str, str] | None:
    global _creds, _creds_loaded
    if _creds_loaded:
        return _creds
    _creds_loaded = True
    try:
        resp = boto3.client("ssm").get_parameters_by_path(
            Path=SSM_SMTP_PATH, WithDecryption=True
        )
        vals = {p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in resp["Parameters"]}
        _creds = (vals["user"], vals["password"])
    except Exception as e:
        Logger.log("WARNING", f"mailer: SMTP credentials unavailable at {SSM_SMTP_PATH} ({e})")
        _creds = None
    return _creds


def is_configured() -> bool:
    return _load_creds() is not None


def send_email(to: str, subject: str, html: str) -> bool:
    creds = _load_creds()
    if creds is None:
        Logger.log("WARNING", f"mailer: dropping '{subject}' to {to}, no SMTP configured")
        return False

    user, password = creds
    msg = EmailMessage()
    msg["From"] = f"CDTs <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("Abre este correo en un cliente compatible con HTML.")
    msg.add_alternative(html, subtype="html")

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=15) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception as e:
        Logger.log("ERROR", f"mailer: failed to send '{subject}' to {to}: {e}")
        return False
