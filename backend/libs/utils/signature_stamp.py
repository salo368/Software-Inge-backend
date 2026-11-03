"""Overlays the signer's drawn signature (PNG) onto the source PDF at
`sign_location`. Ported from
services/signatures/_legacy/utils/stamp.py -- the coordinate format is
already exactly what `sign_location` uses:

    {
        "page":       int (1-indexed),
        "x_pct":      0-100  # from LEFT of the page
        "y_pct":      0-100  # from TOP of the page (UI-friendly)
        "width_pct":  0-100  # optional, defaults to _DEFAULT_WIDTH_PCT
        "height_pct": 0-100  # optional; if absent, derived from the
                             # drawing's own aspect ratio
    }

The stamped PDF is what signature_ca.sign_pdf_pades_b then signs, so
any tampering with the drawing after signing would break the PAdES hash.
"""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

_DEFAULT_WIDTH_PCT = 25.0


def stamp_drawing_on_pdf(pdf_bytes: bytes, drawing_png: bytes, sign_location: dict) -> bytes:
    """Overlays `drawing_png` at `sign_location` on the given PDF.
    Aspect-preserving unless height_pct is explicit. Only the target
    page is mutated. Not idempotent -- calling twice stamps twice."""
    if not pdf_bytes:
        raise ValueError("pdf_bytes is required")
    if not drawing_png:
        raise ValueError("drawing_png is required")

    reader = PdfReader(BytesIO(pdf_bytes))
    page_idx = int(sign_location["page"]) - 1
    if page_idx < 0 or page_idx >= len(reader.pages):
        raise ValueError(
            f"sign_location.page {sign_location['page']} out of range "
            f"(PDF has {len(reader.pages)} pages)"
        )

    page = reader.pages[page_idx]
    mediabox = page.mediabox
    page_w = float(mediabox.width)
    page_h = float(mediabox.height)

    width_pct = float(sign_location.get("width_pct", _DEFAULT_WIDTH_PCT))
    if not (0 < width_pct <= 100):
        raise ValueError("width_pct must be in (0, 100]")
    box_w = page_w * (width_pct / 100.0)

    drawing = ImageReader(BytesIO(drawing_png))
    iw, ih = drawing.getSize()
    if iw <= 0 or ih <= 0:
        raise ValueError("drawing_png has zero dimensions")

    height_pct = sign_location.get("height_pct")
    if height_pct is not None:
        height_pct = float(height_pct)
        if not (0 < height_pct <= 100):
            raise ValueError("height_pct must be in (0, 100]")
        box_h = page_h * (height_pct / 100.0)
    else:
        box_h = box_w * (ih / iw)

    x_pct = float(sign_location["x_pct"])
    y_pct = float(sign_location["y_pct"])
    if not (0 <= x_pct <= 100 and 0 <= y_pct <= 100):
        raise ValueError("x_pct/y_pct must be in [0, 100]")

    llx = page_w * (x_pct / 100.0)
    # y_pct is from the TOP (UI convention); PDF origin is BOTTOM-LEFT.
    ury = page_h - page_h * (y_pct / 100.0)
    lly = ury - box_h

    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.drawImage(drawing, llx, lly, width=box_w, height=box_h, mask="auto")
    c.save()

    stamp_reader = PdfReader(BytesIO(buf.getvalue()))
    page.merge_page(stamp_reader.pages[0])

    writer = PdfWriter()
    writer.append(reader)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()
