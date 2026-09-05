import os
import secrets
from datetime import datetime, timezone
from io import BytesIO

import boto3
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as pdf_canvas

from utils.auth.middleware import require_auth
from utils.http import err, ok, parse_body
from utils.mailer import send_email
from utils.orm.models import Cdts, DigitalSignatures

BUCKET = os.environ["FILES_BUCKET"]
SIGN_FRONT_URL = os.environ["SIGN_FRONT_URL"]
s3 = boto3.client("s3")

# Posicion por defecto del recuadro de firma (top-left, % de la pagina).
# Coincide con la linea "Firma del cliente" del contrato generado.
DEFAULT_PAGE, DEFAULT_X, DEFAULT_Y = 1, 15, 70


def _contract_pdf(user, cdt) -> bytes:
    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=letter)
    w, h = letter

    c.setFillColorRGB(0.09, 0.08, 0.23)
    c.rect(0, h - 70, w, 70, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, h - 45, "CDTs")
    c.setFont("Helvetica", 10)
    c.drawRightString(w - 50, h - 45, datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 110, f"Contrato de apertura CDT #{cdt.id}")

    c.setFont("Helvetica", 11)
    y = h - 145
    for line in (
        f"Titular: {user.name} (@{user.username})",
        f"Monto de inversion: ${cdt.amount:,.2f} COP",
        f"Plazo: {cdt.term} dias",
        f"Tasa efectiva anual: {cdt.rate}%",
        f"Fecha de apertura: {cdt.opened_at.strftime('%Y-%m-%d')}",
    ):
        c.drawString(50, y, line)
        y -= 20

    c.setFont("Helvetica", 9)
    y -= 12
    for line in (
        "El titular declara que los recursos invertidos provienen de actividades licitas y acepta las",
        "condiciones del deposito a termino fijo: el capital permanecera invertido durante el plazo",
        "pactado y los rendimientos se liquidaran al vencimiento a la tasa aqui establecida.",
        "Este documento se firma electronicamente y tiene plena validez juridica.",
    ):
        c.drawString(50, y, line)
        y -= 14

    line_y = h * (1 - 0.79)
    c.line(w * 0.15, line_y, w * 0.43, line_y)
    c.drawString(w * 0.15, line_y - 14, "Firma del cliente")

    c.showPage()
    c.save()
    return buf.getvalue()


def _email_html(name: str, cdt_id: int, sign_url: str) -> str:
    return f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: auto;">
      <h2 style="color:#4c1d95;">CDTs — Firma digital</h2>
      <p>Hola {name},</p>
      <p>Tu contrato de apertura del <b>CDT #{cdt_id}</b> está listo para firmar.
      El proceso toma menos de 3 minutos.</p>
      <p style="text-align:center; margin: 28px 0;">
        <a href="{sign_url}" style="background:#7c3aed; color:#fff; padding: 12px 28px;
           border-radius: 8px; text-decoration: none; font-weight: bold;">Firmar mi contrato</a>
      </p>
      <p style="color:#6b7280; font-size: 13px;">Si no solicitaste esta firma, ignora este correo.</p>
    </div>
    """


@require_auth
def create(event, context):
    body = parse_body(event)
    if body is None:
        return err(400, "invalid_json")

    email = (body.get("email") or "").strip().lower()
    cdt_id = body.get("cdt_id")
    if not email or "@" not in email or not cdt_id:
        return err(400, "missing_fields", "email y cdt_id son requeridos")

    user = event["auth"].user
    cdt = Cdts.get_by_id(cdt_id)
    if cdt is None or cdt.user_id != user.id:
        return err(404, "cdt_not_found")
    if cdt.stage != "firma":
        return err(409, "cdt_not_in_firma")

    token = secrets.token_urlsafe(24)
    pdf_key = f"processes/{token}/contract.pdf"
    s3.put_object(
        Bucket=BUCKET, Key=pdf_key,
        Body=_contract_pdf(user, cdt), ContentType="application/pdf",
    )

    row = DigitalSignatures.create(
        cdt_id=cdt.id,
        token=token,
        email=email,
        stage="revision",
        pdf_key=pdf_key,
        page=int(body.get("page", DEFAULT_PAGE)),
        pos_x=body.get("x", DEFAULT_X),
        pos_y=body.get("y", DEFAULT_Y),
    )

    sign_url = f"{SIGN_FRONT_URL}/s/{token}"
    send_email(email, f"Firma tu contrato de CDT #{cdt.id}", _email_html(user.name, cdt.id, sign_url))
    return ok(201, {"id": row.id, "sign_url": sign_url, "email": email})
