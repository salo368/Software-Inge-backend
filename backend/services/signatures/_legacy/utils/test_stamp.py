"""Unit tests for `services/signatures/utils/stamp.py`.

Cross-cutting because the module is block-local to signatures but the
tests here need a real PDF + a real PNG (generated in memory) to exercise
the reportlab -> pypdf overlay pipeline. Same sys.path escape hatch as
`test_mock_ca.py`.

What we assert:

    * Overlay is placed on the right page (position + size derived from
      MediaBox with the UI's top-anchored y_pct).
    * The resulting PDF still parses cleanly and preserves page count.
    * Missing / out-of-range page raises ValueError before touching the
      output.
    * A blank drawing raises ValueError early (defensive).
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[4]
_SIG_UTILS = _BACKEND / "services" / "signatures" / "utils"
sys.path.insert(0, str(_SIG_UTILS))

for _n in list(sys.modules):
    if _n == "utils" or _n.startswith("utils."):
        sys.modules.pop(_n, None)

import stamp  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sample_pdf(pages: int = 1) -> bytes:
    """Generates a small multi-page PDF with reportlab so we know the
    exact MediaBox we're overlaying onto (A4 by default)."""
    from reportlab.pdfgen import canvas as pdf_canvas

    buf = BytesIO()
    c = pdf_canvas.Canvas(buf)
    for i in range(pages):
        c.drawString(100, 750, f"Page {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def _sample_png(w: int = 300, h: int = 100) -> bytes:
    """Generates a tiny PNG with reportlab's PIL bridge. Content is a
    solid rectangle; we only care about shape/aspect for stamp tests."""
    from PIL import Image

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for x in range(w):
        img.putpixel((x, h // 2), (0, 0, 0, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _default_location(**overrides) -> dict:
    loc = {"page": 1, "x_pct": 20.0, "y_pct": 30.0, "width_pct": 25.0}
    loc.update(overrides)
    return loc


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
class TestValidation:
    def test_missing_pdf_raises(self):
        with pytest.raises(ValueError):
            stamp.stamp_drawing_on_pdf(b"", _sample_png(), _default_location())

    def test_missing_drawing_raises(self):
        with pytest.raises(ValueError):
            stamp.stamp_drawing_on_pdf(_sample_pdf(), b"", _default_location())

    def test_page_out_of_range_raises(self):
        with pytest.raises(ValueError):
            stamp.stamp_drawing_on_pdf(
                _sample_pdf(pages=2), _sample_png(), _default_location(page=5)
            )

    def test_page_zero_raises(self):
        with pytest.raises(ValueError):
            stamp.stamp_drawing_on_pdf(
                _sample_pdf(), _sample_png(), _default_location(page=0)
            )

    def test_x_pct_out_of_range_raises(self):
        with pytest.raises(ValueError):
            stamp.stamp_drawing_on_pdf(
                _sample_pdf(),
                _sample_png(),
                _default_location(x_pct=150),
            )

    def test_width_pct_zero_raises(self):
        with pytest.raises(ValueError):
            stamp.stamp_drawing_on_pdf(
                _sample_pdf(),
                _sample_png(),
                _default_location(width_pct=0),
            )


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------
class TestOutput:
    def test_output_is_valid_pdf(self):
        out = stamp.stamp_drawing_on_pdf(
            _sample_pdf(), _sample_png(), _default_location()
        )
        assert out.startswith(b"%PDF")
        # Roundtrip-parse it to catch any structural corruption.
        from pypdf import PdfReader

        r = PdfReader(BytesIO(out))
        assert len(r.pages) == 1

    def test_page_count_preserved_multipage(self):
        pdf = _sample_pdf(pages=3)
        out = stamp.stamp_drawing_on_pdf(
            pdf, _sample_png(), _default_location(page=2)
        )
        from pypdf import PdfReader

        r = PdfReader(BytesIO(out))
        assert len(r.pages) == 3

    def test_default_height_uses_drawing_aspect(self, monkeypatch):
        """When height_pct is not provided, box height derives from the
        drawing's own aspect ratio (drawing_h/drawing_w). We verify by
        stubbing the Canvas.drawImage call and asserting the height
        passed to it matches width * (ih/iw)."""
        captured = {}

        def _canvas_factory(orig_canvas_class):
            class Spy(orig_canvas_class):
                def drawImage(self, img, x, y, width, height, mask="auto"):
                    captured["x"] = x
                    captured["y"] = y
                    captured["w"] = width
                    captured["h"] = height
                    return super().drawImage(img, x, y, width, height, mask=mask)

            return Spy

        # 300 x 100 PNG -> aspect 1/3, so height should be width / 3.
        drawing = _sample_png(300, 100)
        pdf = _sample_pdf()

        # Patch reportlab's Canvas class inside the stamp module.
        original = stamp.pdf_canvas.Canvas
        stamp.pdf_canvas.Canvas = _canvas_factory(original)
        try:
            stamp.stamp_drawing_on_pdf(
                pdf, drawing, _default_location(width_pct=40)
            )
        finally:
            stamp.pdf_canvas.Canvas = original

        assert captured["h"] == pytest.approx(captured["w"] * (100 / 300), rel=1e-3)

    def test_explicit_height_pct_honoured(self):
        """When height_pct is set, the drawing is letterboxed into that
        exact box regardless of its native aspect ratio."""
        captured = {}
        original = stamp.pdf_canvas.Canvas

        class Spy(original):
            def drawImage(self, img, x, y, width, height, mask="auto"):
                captured["h"] = height
                return super().drawImage(img, x, y, width, height, mask=mask)

        stamp.pdf_canvas.Canvas = Spy
        try:
            stamp.stamp_drawing_on_pdf(
                _sample_pdf(),
                _sample_png(300, 100),
                _default_location(width_pct=40, height_pct=15),
            )
        finally:
            stamp.pdf_canvas.Canvas = original

        # A4 height ~= 841.89 pt, 15% = ~126.3 pt.
        assert captured["h"] == pytest.approx(841.89 * 0.15, rel=1e-3)


# ---------------------------------------------------------------------------
# Coordinate mapping (UI top-left -> PDF bottom-left)
# ---------------------------------------------------------------------------
class TestCoordinates:
    def test_y_pct_flipped_to_pdf_native(self):
        """y_pct=0 (top of page) should place the box near the top of
        the PDF, i.e. lly close to page_h - box_h. y_pct=100 (bottom of
        page) places lly close to -box_h (drawing off the page bottom,
        which the caller is expected to avoid, but the math still holds).
        """
        captured = []
        original = stamp.pdf_canvas.Canvas

        class Spy(original):
            def drawImage(self, img, x, y, width, height, mask="auto"):
                captured.append({"y": y, "height": height})
                return super().drawImage(img, x, y, width, height, mask=mask)

        stamp.pdf_canvas.Canvas = Spy
        try:
            # Top of page: box top should touch page top. `y` is bottom
            # of the box in PDF native coords, so it equals page_h - box_h.
            stamp.stamp_drawing_on_pdf(
                _sample_pdf(),
                _sample_png(300, 100),
                _default_location(y_pct=0),
            )
        finally:
            stamp.pdf_canvas.Canvas = original

        top_case = captured[0]
        # A4 height ~= 841.89. width_pct=25 -> box_w=595.28*0.25=148.82
        # box_h = 148.82 * (100/300) ~= 49.61. Expected y = 841.89 - 49.61.
        assert top_case["y"] == pytest.approx(841.89 - top_case["height"], rel=1e-3)
