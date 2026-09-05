import hashlib
import os
from datetime import datetime, timezone
from io import BytesIO

import boto3
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

from utils.http import err, ok, parse_body
from utils.orm.models import Cdts, DigitalSignatures, Files

BUCKET = os.environ["FILES_BUCKET"]
COMMERCE_URL = os.environ["COMMERCE_URL"]
s3 = boto3.client("s3")

MAX_ATTEMPTS = 3
BOX_WIDTH_PCT = 28  # ancho del recuadro de firma como % del ancho de pagina


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
    sig = s3.get_object(Bucket=BUCKET, Key=row.signature_key)["Body"].read()
    signed = _stamp(pdf, sig, row.page, float(row.pos_x), float(row.pos_y))

    signed_key = f"processes/{token}/signed.pdf"
    s3.put_object(Bucket=BUCKET, Key=signed_key, Body=signed, ContentType="application/pdf")

    s3_uri = f"s3://{BUCKET}/{signed_key}"
    DigitalSignatures.update_by_id(row.id, {
        "stage": "firmado",
        "signed_pdf_key": signed_key,
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
    })
