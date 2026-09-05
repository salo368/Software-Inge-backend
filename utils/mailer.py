"""Envio de correos via SMTP de Gmail. Credenciales en SSM:

    /cdts/{stage}/smtp/user      -> correo remitente (String)
    /cdts/{stage}/smtp/password  -> app password de Gmail (SecureString)
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

import boto3

_creds: tuple[str, str] | None = None


def _load_creds() -> tuple[str, str]:
    global _creds
    if _creds is None:
        stage = os.environ.get("STAGE", "dev")
        ssm = boto3.client("ssm")
        resp = ssm.get_parameters_by_path(Path=f"/cdts/{stage}/smtp", WithDecryption=True)
        vals = {p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in resp["Parameters"]}
        _creds = (vals["user"], vals["password"])
    return _creds


def send_email(to: str, subject: str, html: str) -> None:
    user, password = _load_creds()
    msg = EmailMessage()
    msg["From"] = f"CDTs <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("Abre este correo en un cliente compatible con HTML.")
    msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=15) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
