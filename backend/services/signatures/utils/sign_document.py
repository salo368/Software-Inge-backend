"""Stamps the drawn signature onto the order and appends the audit page.

The hash printed on the certificate is taken over the *stamped* document,
before the certificate itself is appended, so it can be recomputed later by
dropping the last page.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

from utils.investment_order import (
    BRAND_DEEPER,
    CONTENT_W,
    INK,
    LINE,
    MARGIN,
    MUTED,
    PAGE_H,
    PAGE_W,
    POSITIVE,
    POSITIVE_TINT,
    SIGNATURE_WIDTH_PCT,
    TINT,
    WHITE,
    gradient_band,
)

EVIDENCE_LABELS = (
    ("id_front", "ID document (front)"),
    ("id_back", "ID document (back)"),
    ("face", "Signer face capture"),
)


def stamp_signature(pdf_bytes: bytes, signature_png: bytes,
                    page_no: int, x_pct: float, y_pct: float) -> bytes:
    reader = PdfReader(BytesIO(pdf_bytes))
    page = reader.pages[page_no - 1]
    w = float(page.mediabox.width)
    h = float(page.mediabox.height)

    img = ImageReader(BytesIO(signature_png))
    iw, ih = img.getSize()
    box_w = w * SIGNATURE_WIDTH_PCT / 100
    box_h = box_w * ih / iw
    x = w * x_pct / 100
    y = h * (1 - y_pct / 100)

    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(w, h))
    c.drawImage(img, x, y, width=box_w, height=box_h, mask="auto")
    c.save()

    page.merge_page(PdfReader(buf).pages[0])
    writer = PdfWriter()
    writer.append(reader)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _fitted_image(c, img_bytes: bytes, x: float, y: float, max_w: float, max_h: float) -> None:
    c.setFillColor(WHITE)
    c.setStrokeColor(LINE)
    c.roundRect(x, y, max_w, max_h, 6, stroke=1, fill=1)
    img = ImageReader(BytesIO(img_bytes))
    iw, ih = img.getSize()
    scale = min((max_w - 8) / iw, (max_h - 8) / ih)
    dw, dh = iw * scale, ih * scale
    c.drawImage(img, x + (max_w - dw) / 2, y + (max_h - dh) / 2,
                width=dw, height=dh, mask="auto")


def build_certificate(*, signature, order_number: str, holder_name: str,
                      images: dict[str, bytes], doc_hash: str,
                      signed_at: datetime) -> bytes:
    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=letter)

    band_h = 92
    gradient_band(c, PAGE_H - band_h, band_h)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(MARGIN, PAGE_H - 46, "Certificado de firma electrónica")
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN, PAGE_H - 63, f"Orden de inversión N.° {order_number}")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 46, "CDTs")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 63,
                      signed_at.strftime("%d/%m/%Y %H:%M UTC"))

    y = PAGE_H - band_h - 30

    c.setFillColor(POSITIVE_TINT)
    c.setStrokeColor(POSITIVE)
    c.roundRect(MARGIN, y - 40, CONTENT_W, 40, 8, stroke=1, fill=1)
    c.setFillColor(POSITIVE)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(MARGIN + 16, y - 18, "Documento firmado y verificado")
    c.setFont("Helvetica", 8.4)
    c.drawString(MARGIN + 16, y - 31,
                 "Identidad validada automáticamente y confirmada con un código de un solo uso enviado al correo del titular.")
    y -= 66

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, y, "Datos de la ceremonia")
    y -= 18

    rows = [
        ("Firmante", holder_name),
        ("Correo verificado", signature.email),
        ("Identificador de firma", str(signature.id)),
        ("Fecha y hora (UTC)", signed_at.strftime("%Y-%m-%d %H:%M:%S")),
        ("Método de autenticación", "OTP de 6 dígitos por correo electrónico"),
        ("Validación de identidad", "Amazon Rekognition — OCR de documento y detección facial"),
    ]
    for label, value in rows:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 8.5)
        c.drawString(MARGIN, y, label.upper())
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN + 170, y, value)
        y -= 15
    y -= 14

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, y, "Evidencias de identidad")
    y -= 12

    box_w, box_h = 152, 104
    gap = (CONTENT_W - 3 * box_w) / 2
    x = MARGIN
    for key, label in EVIDENCE_LABELS:
        _fitted_image(c, images[key], x, y - box_h, box_w, box_h)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.6)
        c.drawString(x + 2, y - box_h - 11, label)
        x += box_w + gap
    y -= box_h + 34

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, y, "Firma manuscrita registrada")
    y -= 12
    _fitted_image(c, images["signature"], MARGIN, y - 78, 236, 78)
    y -= 100

    c.setFillColor(TINT)
    c.setStrokeColor(LINE)
    c.roundRect(MARGIN, y - 54, CONTENT_W, 54, 8, stroke=1, fill=1)
    c.setFillColor(BRAND_DEEPER)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN + 14, y - 18, "HASH DE AUTENTICIDAD — SHA-256")
    c.setFillColor(INK)
    c.setFont("Courier-Bold", 8.6)
    c.drawString(MARGIN + 14, y - 33, doc_hash[:64])
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.2)
    c.drawString(MARGIN + 14, y - 46,
                 "Calculado sobre el documento firmado sin esta hoja. Cualquier alteración posterior lo invalida.")
    y -= 74

    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.2)
    for line in (
        "Este certificado hace parte integral del documento firmado y constituye la evidencia de la manifestación de voluntad del titular,",
        "conforme a la Ley 527 de 1999 sobre comercio electrónico y firmas digitales en Colombia.",
    ):
        c.drawString(MARGIN, y, line)
        y -= 10

    c.setStrokeColor(LINE)
    c.line(MARGIN, 44, PAGE_W - MARGIN, 44)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(MARGIN, 32, "CDTs — Certificado de firma electrónica")
    c.drawRightString(PAGE_W - MARGIN, 32, f"Orden {order_number}")

    c.showPage()
    c.save()
    return buf.getvalue()


def append_pdf(base: bytes, extra: bytes) -> bytes:
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(base)))
    writer.append(PdfReader(BytesIO(extra)))
    out = BytesIO()
    writer.write(out)
    return out.getvalue()
