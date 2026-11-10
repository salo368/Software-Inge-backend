"""Unit tests for `libs.utils.signature_audit_page`.

Renders real PDFs (reportlab + bundled IBM Plex fonts) and reads them back
with pypdf -- no mocks, the point is to catch layout code that crashes or
silently drops data on unusual inputs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from PIL import Image
from pypdf import PdfReader

from libs.utils.signature_audit_page import build_audit_page


def _png(w: int, h: int) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), (200, 200, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _render(**overrides) -> str:
    kwargs = dict(
        signature_id="36a151f2-c080-4f1f-bc3c-76258f17d1fc",
        signatory="Camila Ríos Peñaranda",
        email="camila@example.com",
        id_front_png=_png(900, 560),
        id_back_png=_png(900, 560),
        face_png=_png(128, 128),
        draw_png=_png(400, 150),
        signed_at=datetime(2026, 11, 3, 3, 51, 59, tzinfo=timezone.utc),
        cert_serial="193545c9e05892081f9c1c33f9e03ddd",
        document_hash="06b386917c46bd323f30b095e0774c555b9c55c7bd612d270f4161b74387446e",
        signing_data={"ip": "186.121.65.78", "user_agent": "curl/8.1.2",
                      "resolved_at": "2026-11-03T03:51:53.855499+00:00"},
    )
    kwargs.update(overrides)
    pdf = build_audit_page(**kwargs)
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 1
    return reader.pages[0].extract_text()


def test_renders_signer_hash_and_telemetry():
    text = _render()

    assert "Camila Ríos Peñaranda" in text
    assert "camila@example.com" in text
    assert "3 de noviembre de 2026" in text
    assert "06b386917c46bd323f30b095e0774c555b9c55c7bd612d270f4161b74387446e" in text
    assert "193545c9e05892081f9c1c33f9e03ddd" in text
    assert "186.121.65.78" in text
    assert "03/11/2026 a las 03:51:53 UTC" in text


def test_missing_signing_data_renders_dashes():
    text = _render(signing_data=None)

    assert "Dirección IP" in text
    assert "validado el" not in text


def test_very_long_user_agent_is_wrapped_not_truncated():
    long_ua = "Mozilla/5.0 " + "(Linux; Android 16; SM-S721B Build/BP2A.250605.031.A3; wv) " * 5
    text = _render(signing_data={"ip": "1.2.3.4", "user_agent": long_ua})

    assert "BP2A.250605.031.A3" in text
