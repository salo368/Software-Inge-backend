import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from utils.http import err, ok
from utils.mailer import send_email
from utils.orm.models import DigitalSignatures


def _email_html(otp: str) -> str:
    return f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: auto;">
      <h2 style="color:#4c1d95;">CDTs — Código de firma</h2>
      <p>Tu código para confirmar la firma es:</p>
      <p style="text-align:center; font-size: 34px; letter-spacing: 10px;
         font-weight: bold; color:#17143a; margin: 24px 0;">{otp}</p>
      <p style="color:#6b7280; font-size: 13px;">Vence en 10 minutos. Si no fuiste tú, ignora este correo.</p>
    </div>
    """


def request_otp(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = DigitalSignatures.get_by_token(token)
    if row is None:
        return err(404, "process_not_found")
    if row.stage == "firmado":
        return err(409, "already_signed")
    if not row.signature_key:
        return err(409, "signature_missing")

    otp = f"{secrets.randbelow(1_000_000):06d}"
    DigitalSignatures.update_by_id(row.id, {
        "otp_hash": hashlib.sha256(otp.encode()).hexdigest(),
        "otp_expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "otp_attempts": 0,
        "stage": "otp",
    })
    send_email(row.email, "Tu código de firma CDTs", _email_html(otp))
    return ok(200, {"status": "sent"})
