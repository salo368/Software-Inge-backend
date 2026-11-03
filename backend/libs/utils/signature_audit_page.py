"""Builds the audit/evidence page appended to the end of every signed
PDF: a reusable template with a 2x2 grid of the ID front/back photos,
the selfie and the drawn signature, plus the signing metadata (who,
when, from where). Inspired by the kind of audit page e-signature
providers like ZapSign attach to their own signed PDFs.

Not a legacy port -- this is new. The layout is fixed and identical
across every signature so a future reader never has to guess where
anything is.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Optional

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

PAGE_W, PAGE_H = LETTER

_MARGIN = 50
_GRID_GAP = 20
_CELL_W = (PAGE_W - 2 * _MARGIN - _GRID_GAP) / 2
_CELL_H = 200


def _draw_cell(c: pdf_canvas.Canvas, image_bytes: bytes, x: float, y: float, label: str) -> None:
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.rect(x, y, _CELL_W, _CELL_H, stroke=1, fill=0)
    if image_bytes:
        img = ImageReader(BytesIO(image_bytes))
        iw, ih = img.getSize()
        scale = min((_CELL_W - 10) / iw, (_CELL_H - 30) / ih)
        draw_w, draw_h = iw * scale, ih * scale
        c.drawImage(
            img,
            x + (_CELL_W - draw_w) / 2,
            y + 20 + (_CELL_H - 30 - draw_h) / 2,
            width=draw_w,
            height=draw_h,
            mask="auto",
            preserveAspectRatio=True,
        )
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawCentredString(x + _CELL_W / 2, y + 6, label)
    c.setFillColorRGB(0, 0, 0)


def build_audit_page(
    *,
    signature_id: str,
    signatory: Optional[str],
    email: Optional[str],
    id_front_png: bytes,
    id_back_png: bytes,
    face_png: bytes,
    draw_png: bytes,
    signed_at: datetime,
    cert_serial: str,
    document_hash: str,
    signing_data: Optional[dict],
) -> bytes:
    """Returns a single-page PDF (Letter size) with the evidence grid
    and signing metadata.

    Must be appended to the document BEFORE the PAdES signature is
    applied, not after -- a PAdES signature only covers the bytes that
    existed at signing time, so anything appended afterward makes the
    document read back as tampered ("document_integrity: False") even
    though nothing malicious happened. `document_hash` is therefore the
    hash of the document as it stood right before this page gets
    appended and the whole thing gets signed, not a hash of the final
    signed file (which doesn't exist yet when this runs).
    """
    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=LETTER)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(_MARGIN, PAGE_H - 50, "Evidencia de Firma Electronica")

    # 2x2 grid: top row is the ID, bottom row is face (left) + drawn
    # signature (right) -- fixed order, same for every signature.
    grid_top = PAGE_H - 90
    row1_y = grid_top - _CELL_H
    row2_y = row1_y - _GRID_GAP - _CELL_H
    col1_x = _MARGIN
    col2_x = _MARGIN + _CELL_W + _GRID_GAP

    _draw_cell(c, id_front_png, col1_x, row1_y, "Cedula - Frente")
    _draw_cell(c, id_back_png, col2_x, row1_y, "Cedula - Reverso")
    _draw_cell(c, face_png, col1_x, row2_y, "Rostro (selfie)")
    _draw_cell(c, draw_png, col2_x, row2_y, "Firma dibujada")

    # Metadata block below the grid.
    signing_data = signing_data or {}
    lines = [
        f"ID de la firma: {signature_id}",
        f"Firmante: {signatory or '-'}",
        f"Correo: {email or '-'}",
        f"Fecha y hora de la firma (UTC): {signed_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Serial del certificado: {cert_serial}",
        f"Hash SHA-256 del documento: {document_hash}",
        f"IP: {signing_data.get('ip') or '-'}",
        f"Dispositivo / navegador: {signing_data.get('user_agent') or '-'}",
        f"Idioma del cliente: {signing_data.get('accept_language') or '-'}",
    ]
    text_y = row2_y - 30
    c.setFont("Helvetica", 9)
    for line in lines:
        c.drawString(_MARGIN, text_y, line)
        text_y -= 14

    c.setFont("Helvetica-Oblique", 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(
        _MARGIN, 30,
        "Documento generado automaticamente. Proyecto academico -- sin validez juridica real.",
    )

    c.save()
    return buf.getvalue()
