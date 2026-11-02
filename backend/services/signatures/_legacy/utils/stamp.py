"""Overlays the signer's drawn signature (PNG) onto the source PDF at
the location captured at ceremony creation.

Uses pypdf to write into the PDF and reportlab to render the PNG onto a
page-sized canvas that is then merged into the target page. Both libs
are already runtime dependencies of the signatures service.

Coordinate convention (matches `create` handler and `mock_ca`):

    signature_location = {
        "page":       int (1-indexed),
        "x_pct":      0-100  # from LEFT of the page
        "y_pct":      0-100  # from TOP of the page (UI-friendly)
        "width_pct":  0-100  # optional, defaults to _DEFAULT_WIDTH_PCT
        "height_pct": 0-100  # optional; if absent, height is derived
                             # from the drawing aspect ratio so it doesn't
                             # distort.
    }

The stamped PDF is what `mock_ca.sign_pdf_pades_b` then signs -- so any
tampering with the drawing after signing would break the PAdES hash.
"""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas


_DEFAULT_WIDTH_PCT = 25.0


def stamp_drawing_on_pdf(
    pdf_bytes: bytes,
    drawing_png: bytes,
    signature_location: dict,
) -> bytes:
    """Overlays `drawing_png` at `signature_location` on the given PDF.

    * The drawing is aspect-preserving-scaled: `width_pct` fixes the
      width and `box_h` is derived from the drawing's own aspect ratio
      unless `height_pct` is explicitly provided (in which case we
      letterbox it into the requested box).
    * Only the target page is mutated; the others pass through
      untouched.

    Returns the resulting PDF as bytes. Not idempotent -- calling twice
    stamps two copies.
    """
    if not pdf_bytes:
        raise ValueError("pdf_bytes is required")
    if not drawing_png:
        raise ValueError("drawing_png is required")

    reader = PdfReader(BytesIO(pdf_bytes))
    page_idx = int(signature_location["page"]) - 1
    if page_idx < 0 or page_idx >= len(reader.pages):
        raise ValueError(
            f"signature_location.page {signature_location['page']} out of range "
            f"(PDF has {len(reader.pages)} pages)"
        )

    page = reader.pages[page_idx]
    mediabox = page.mediabox
    page_w = float(mediabox.width)
    page_h = float(mediabox.height)

    width_pct = float(signature_location.get("width_pct", _DEFAULT_WIDTH_PCT))
    if not (0 < width_pct <= 100):
        raise ValueError("width_pct must be in (0, 100]")
    box_w = page_w * (width_pct / 100.0)

    drawing = ImageReader(BytesIO(drawing_png))
    iw, ih = drawing.getSize()
    if iw <= 0 or ih <= 0:
        raise ValueError("drawing_png has zero dimensions")

    # If the caller passed an explicit height, honour it; otherwise the
    # drawing scales aspect-preserving from its own iw/ih ratio.
    height_pct = signature_location.get("height_pct")
    if height_pct is not None:
        height_pct = float(height_pct)
        if not (0 < height_pct <= 100):
            raise ValueError("height_pct must be in (0, 100]")
        box_h = page_h * (height_pct / 100.0)
    else:
        box_h = box_w * (ih / iw)

    x_pct = float(signature_location["x_pct"])
    y_pct = float(signature_location["y_pct"])
    if not (0 <= x_pct <= 100 and 0 <= y_pct <= 100):
        raise ValueError("x_pct/y_pct must be in [0, 100]")

    llx = page_w * (x_pct / 100.0)
    # y_pct is from the TOP of the page (UI convention); PDF native
    # origin is BOTTOM-LEFT, so we flip. `ury` is where the top of the
    # drawing lands; `lly` is derived by subtracting box_h.
    ury = page_h - page_h * (y_pct / 100.0)
    lly = ury - box_h

    # Draw the PNG onto a transparent, page-sized canvas so we can
    # merge it as an overlay. `mask='auto'` lets reportlab honour the
    # PNG alpha channel (the drawn signature is on a transparent
    # background).
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
