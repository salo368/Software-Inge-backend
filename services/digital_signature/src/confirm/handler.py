import hashlib
import os
from datetime import datetime, timezone
from io import BytesIO

import boto3
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

from utils.http import err, ok, parse_body
from utils.orm.models import Cdts, DigitalSignatures, Files

BUCKET = os.environ["FILES_BUCKET"]
COMMERCE_URL = os.environ["COMMERCE_URL"]
s3 = boto3.client("s3")

MAX_ATTEMPTS = 3
BOX_WIDTH_PCT = 28  # ancho del recuadro de firma como % del ancho de pagina

EVIDENCE_KEYS = ("cedula_front", "cedula_back", "face", "signature")


def _stamp(pdf_bytes: bytes, sig_bytes: bytes, page_no: int, x_pct: float, y_pct: float) -> bytes:
    reader = PdfReader(BytesIO(pdf_bytes))
    page = reader.pages[page_no - 1]
    w = float(page.mediabox.width)
    h = float(page.mediabox.height)

    img = ImageReader(BytesIO(sig_bytes))
    iw, ih = img.getSize()
    box_w = w * BOX_WIDTH_PCT / 100
    box_h = box_w * ih / iw
    x = w * x_pct / 100
    y = h * (1 - y_pct / 100) - box_h

    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(w, h))
    c.drawImage(img, x, y, width=box_w, height=box_h, mask="auto")
    c.save()

    overlay = PdfReader(buf).pages[0]
    page.merge_page(overlay)
    writer = PdfWriter()
    writer.append(reader)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _draw_fitted(c, img_bytes: bytes, x: float, y: float, max_w: float, max_h: float) -> None:
    img = ImageReader(BytesIO(img_bytes))
    iw, ih = img.getSize()
    scale = min(max_w / iw, max_h / ih)
    dw, dh = iw * scale, ih * scale
    c.drawImage(img, x + (max_w - dw) / 2, y + (max_h - dh) / 2, width=dw, height=dh, mask="auto")
    c.setStrokeColorRGB(0.85, 0.84, 0.92)
    c.rect(x, y, max_w, max_h, stroke=1, fill=0)


def _audit_page(row, images: dict[str, bytes], doc_hash: str, signed_at: datetime) -> bytes:
    """Hoja de certificado: evidencias de identidad, firma y hash de autenticidad."""
    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=letter)
    w, h = letter

    c.setFillColorRGB(0.09, 0.08, 0.23)
    c.rect(0, h - 70, w, 70, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, h - 45, "Certificado de firma digital")
    c.setFont("Helvetica", 10)
    c.drawRightString(w - 50, h - 45, "CDTs")

    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 10)
    y = h - 100
    for line in (
        f"Proceso de firma: #{row.id}",
        f"CDT asociado: #{row.cdt_id}",
        f"Correo verificado por OTP: {row.email}",
        f"Fecha y hora de firma (UTC): {signed_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ):
        c.drawString(50, y, line)
        y -= 16

    y -= 12
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Evidencias de identidad")
    y -= 10
    box_w, box_h = 160, 110
    x = 50
    for key, label in (
        ("cedula_front", "Cedula - frontal"),
        ("cedula_back", "Cedula - posterior"),
        ("face", "Rostro"),
    ):
        _draw_fitted(c, images[key], x, y - box_h, box_w, box_h)
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.35, 0.35, 0.45)
        c.drawString(x, y - box_h - 12, label)
        c.setFillColorRGB(0, 0, 0)
        x += box_w + 20
    y -= box_h + 40

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Firma registrada")
    y -= 10
    _draw_fitted(c, images["signature"], 50, y - 80, 240, 80)
    y -= 104

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Hash de autenticidad (SHA-256 del documento firmado)")
    y -= 16
    c.setFont("Courier", 9)
    c.drawString(50, y, doc_hash)
    y -= 26
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.35, 0.35, 0.45)
    for line in (
        "Este certificado hace parte integral del documento firmado y garantiza la identidad del firmante.",
        "Cualquier alteracion de las paginas anteriores invalida el hash de autenticidad aqui impreso.",
    ):
        c.drawString(50, y, line)
        y -= 12

    c.showPage()
    c.save()
    return buf.getvalue()


def _append_pdf(base: bytes, extra: bytes) -> bytes:
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(base)))
    writer.append(PdfReader(BytesIO(extra)))
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def confirm(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = DigitalSignatures.get_by_token(token)
    if row is None:
        return err(404, "process_not_found")
    if row.stage == "firmado":
        return err(409, "already_signed")

    body = parse_body(event) or {}
    otp = str(body.get("otp", "")).strip()
    if not row.otp_hash or row.otp_expires_at is None:
        return err(409, "otp_not_requested")
    if row.otp_expires_at < datetime.now(timezone.utc):
        return err(410, "otp_expired")
    if row.otp_attempts >= MAX_ATTEMPTS:
        return err(429, "too_many_attempts")
    if hashlib.sha256(otp.encode()).hexdigest() != row.otp_hash:
        DigitalSignatures.update_by_id(row.id, {"otp_attempts": row.otp_attempts + 1})
        return err(401, "invalid_otp", f"Intentos restantes: {MAX_ATTEMPTS - row.otp_attempts - 1}")

    pdf = s3.get_object(Bucket=BUCKET, Key=row.pdf_key)["Body"].read()
    images = {
        k: s3.get_object(Bucket=BUCKET, Key=getattr(row, f"{k}_key"))["Body"].read()
        for k in EVIDENCE_KEYS
    }

    signed_at = datetime.now(timezone.utc)
    stamped = _stamp(pdf, images["signature"], row.page, float(row.pos_x), float(row.pos_y))
    doc_hash = hashlib.sha256(stamped).hexdigest()
    final = _append_pdf(stamped, _audit_page(row, images, doc_hash, signed_at))

    signed_key = f"processes/{token}/signed.pdf"
    s3.put_object(Bucket=BUCKET, Key=signed_key, Body=final, ContentType="application/pdf")

    s3_uri = f"s3://{BUCKET}/{signed_key}"
    DigitalSignatures.update_by_id(row.id, {
        "stage": "firmado",
        "signed_pdf_key": signed_key,
        "doc_hash": doc_hash,
        "otp_hash": None,
    })
    Cdts.update_by_id(row.cdt_id, {"stage": "pago", "signature_url": s3_uri})
    Files.create(cdt_id=row.cdt_id, type="signed_contract", s3_url=s3_uri)

    signed_url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": BUCKET, "Key": signed_key}, ExpiresIn=900
    )
    return ok(200, {
        "status": "signed",
        "return_url": f"{COMMERCE_URL}/cdt/{row.cdt_id}",
        "signed_pdf_url": signed_url,
        "doc_hash": doc_hash,
    })
