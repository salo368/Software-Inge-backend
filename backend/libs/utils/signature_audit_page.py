"""Builds the evidence page appended to the end of every signed PDF: the
signer, when it was signed, a 2x2 grid with the ID front/back photos, the
selfie and the drawn signature, and the technical data (certificate
serial, document hash, request telemetry). Same fixed layout for every
signature, so a reader never has to guess where anything is.

Must be appended BEFORE the PAdES signature is applied: PAdES only covers
the bytes that existed at signing time, so anything appended afterward
makes the document read back as tampered.

Fonts are IBM Plex (SIL OFL 1.1, see fonts/OFL.txt), bundled as TTF
because reportlab can't embed CFF-flavoured OTF.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas

PAGE_W, PAGE_H = LETTER

_FONTS_DIR = Path(__file__).parent / "fonts"
_SANS = "PlexSans"
_SANS_SEMI = "PlexSans-SemiBold"
_MONO = "PlexMono"

for _name, _file in (
    (_SANS, "IBMPlexSans-Regular.ttf"),
    (_SANS_SEMI, "IBMPlexSans-SemiBold.ttf"),
    (_MONO, "IBMPlexMono-Regular.ttf"),
):
    if _name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_name, str(_FONTS_DIR / _file)))

_INK = HexColor("#14171F")
_MUTED = HexColor("#5B6472")
_HAIRLINE = HexColor("#DDE1E6")
_SURFACE = HexColor("#F4F6F8")
_ACCENT = HexColor("#1F3A5F")
_OK_BG = HexColor("#E6F4EA")
_OK_FG = HexColor("#1E6B36")

_MARGIN = 40
_CONTENT_W = PAGE_W - 2 * _MARGIN

_GRID_GAP = 10
_CELL_W = (_CONTENT_W - _GRID_GAP) / 2
_CELL_H = 140
_CELL_LABEL_H = 22
_CELL_PAD = 8

_LABEL_W = 130
_ROW_GAP = 4

_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _y(top: float) -> float:
    """Layout is written top-down; reportlab's origin is bottom-left."""
    return PAGE_H - top


def _spaced(c: pdf_canvas.Canvas, x: float, top: float, text: str, font: str, size: float,
            color, char_space: float = 0.0) -> None:
    t = c.beginText()
    t.setTextOrigin(x, _y(top))
    t.setFont(font, size)
    t.setCharSpace(char_space)
    t.setFillColor(color)
    t.textOut(text)
    c.drawText(t)


def _eyebrow(c: pdf_canvas.Canvas, x: float, top: float, text: str) -> None:
    _spaced(c, x, top, text.upper(), _SANS_SEMI, 7, _MUTED, char_space=1.1)


def _section_title(c: pdf_canvas.Canvas, top: float, text: str) -> None:
    c.setFillColor(_ACCENT)
    c.rect(_MARGIN, _y(top + 12), 3, 11, stroke=0, fill=1)
    _spaced(c, _MARGIN + 10, top + 10, text, _SANS_SEMI, 11, _INK)


def _format_date(dt: datetime) -> str:
    return f"{dt.day} de {_MONTHS[dt.month - 1]} de {dt.year}"


def _format_resolved_at(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    return f"{dt.strftime('%d/%m/%Y')} a las {dt.strftime('%H:%M:%S')} UTC"


def _draw_cell(c: pdf_canvas.Canvas, image_bytes: Optional[bytes], x: float, top: float, label: str) -> None:
    c.setFillColor(_SURFACE)
    c.setStrokeColor(_HAIRLINE)
    c.setLineWidth(0.6)
    c.roundRect(x, _y(top + _CELL_H), _CELL_W, _CELL_H, 6, stroke=1, fill=1)
    _eyebrow(c, x + 10, top + 15, label)

    if not image_bytes:
        return
    img = ImageReader(BytesIO(image_bytes))
    iw, ih = img.getSize()
    box_w = _CELL_W - 2 * _CELL_PAD
    box_h = _CELL_H - _CELL_LABEL_H - _CELL_PAD
    scale = min(box_w / iw, box_h / ih)
    draw_w, draw_h = iw * scale, ih * scale
    img_x = x + (_CELL_W - draw_w) / 2
    img_top = top + _CELL_LABEL_H + (box_h - draw_h) / 2
    c.drawImage(img, img_x, _y(img_top + draw_h), width=draw_w, height=draw_h, mask="auto")


def _status_pill(c: pdf_canvas.Canvas, right_x: float, top: float, text: str) -> None:
    font_size = 8
    text_w = pdfmetrics.stringWidth(text, _SANS_SEMI, font_size) + len(text) * 0.6
    pill_w = text_w + 26
    pill_h = 20
    x = right_x - pill_w
    c.setFillColor(_OK_BG)
    c.roundRect(x, _y(top + pill_h), pill_w, pill_h, pill_h / 2, stroke=0, fill=1)
    c.setFillColor(_OK_FG)
    c.circle(x + 11, _y(top + pill_h / 2), 2.6, stroke=0, fill=1)
    _spaced(c, x + 18, top + 13.5, text, _SANS_SEMI, font_size, _OK_FG, char_space=0.6)


def _data_row(c: pdf_canvas.Canvas, top: float, label: str, value: str, mono: bool = False) -> float:
    """Draws one label/value row and returns the top of the next row."""
    font = _MONO if mono else _SANS
    size = 8.2 if mono else 8.8
    value_x = _MARGIN + _LABEL_W
    lines = simpleSplit(value, font, size, _CONTENT_W - _LABEL_W) or ["-"]
    line_h = size + 3.5

    _spaced(c, _MARGIN, top + 9, label, _SANS, 8.8, _MUTED)
    for i, line in enumerate(lines):
        _spaced(c, value_x, top + 9 + i * line_h, line, font, size, _INK)

    bottom = top + 9 + (len(lines) - 1) * line_h + 4
    c.setStrokeColor(_HAIRLINE)
    c.setLineWidth(0.5)
    c.line(_MARGIN, _y(bottom + _ROW_GAP / 2), _MARGIN + _CONTENT_W, _y(bottom + _ROW_GAP / 2))
    return bottom + _ROW_GAP + 3


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
    """Returns a single-page PDF (Letter) with the evidence of the signature.

    `document_hash` is the sha256 of the document as it stood right before
    this page is appended and the whole thing is PAdES-signed -- i.e. the
    raw_signed file, not the final signed one (which doesn't exist yet).
    """
    signing_data = signing_data or {}
    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle("Evidencia de firma electrónica")

    # Header
    c.setFillColor(_ACCENT)
    c.rect(0, _y(5), PAGE_W, 5, stroke=0, fill=1)
    _eyebrow(c, _MARGIN, 40, "Certificado de evidencia")
    _spaced(c, _MARGIN, 64, "Firma electrónica", _SANS_SEMI, 22, _INK)
    _spaced(
        c, _MARGIN, 81,
        "Documento firmado con verificación de identidad y código de un solo uso enviado por correo.",
        _SANS, 9, _MUTED,
    )
    _status_pill(c, _MARGIN + _CONTENT_W, 32, "FIRMADO")
    c.setStrokeColor(_HAIRLINE)
    c.setLineWidth(0.6)
    c.line(_MARGIN, _y(95), _MARGIN + _CONTENT_W, _y(95))

    # Signer card
    card_top, card_h = 107, 62
    c.setFillColor(_SURFACE)
    c.roundRect(_MARGIN, _y(card_top + card_h), _CONTENT_W, card_h, 6, stroke=0, fill=1)
    left_x = _MARGIN + 16
    right_x = _MARGIN + _CONTENT_W / 2 + 8
    _eyebrow(c, left_x, card_top + 17, "Firmante")
    _spaced(c, left_x, card_top + 36, signatory or "-", _SANS_SEMI, 14, _INK)
    _spaced(c, left_x, card_top + 51, email or "-", _SANS, 9, _MUTED)
    _eyebrow(c, right_x, card_top + 17, "Fecha y hora de firma")
    _spaced(c, right_x, card_top + 36, _format_date(signed_at), _SANS_SEMI, 12, _INK)
    _spaced(c, right_x, card_top + 51, f"{signed_at.strftime('%H:%M:%S')} UTC", _SANS, 9, _MUTED)

    # Identity evidence grid: ID on top, selfie + drawn signature below.
    _section_title(c, 185, "Evidencia de identidad")
    grid_top = 205
    col1_x = _MARGIN
    col2_x = _MARGIN + _CELL_W + _GRID_GAP
    row2_top = grid_top + _CELL_H + _GRID_GAP
    _draw_cell(c, id_front_png, col1_x, grid_top, "Documento de identidad · frente")
    _draw_cell(c, id_back_png, col2_x, grid_top, "Documento de identidad · reverso")
    _draw_cell(c, face_png, col1_x, row2_top, "Rostro (selfie)")
    _draw_cell(c, draw_png, col2_x, row2_top, "Firma dibujada")

    # Technical data
    tech_top = row2_top + _CELL_H + 16
    _section_title(c, tech_top, "Datos técnicos")
    resolved = _format_resolved_at(signing_data.get("resolved_at"))
    verification = "Código de un solo uso enviado al correo del firmante"
    if resolved:
        verification += f", validado el {resolved}"

    row_top = tech_top + 20
    row_top = _data_row(c, row_top, "ID de la firma", str(signature_id), mono=True)
    row_top = _data_row(c, row_top, "Serial del certificado", cert_serial, mono=True)
    row_top = _data_row(c, row_top, "Hash SHA-256 *", document_hash, mono=True)
    row_top = _data_row(c, row_top, "Verificación", verification)
    row_top = _data_row(c, row_top, "Dirección IP", signing_data.get("ip") or "-")
    row_top = _data_row(c, row_top, "Dispositivo / navegador", signing_data.get("user_agent") or "-")
    _data_row(c, row_top, "Idioma del navegador", signing_data.get("accept_language") or "-")

    # Footer
    footer_top = PAGE_H - 40
    c.setStrokeColor(_HAIRLINE)
    c.line(_MARGIN, _y(footer_top), _MARGIN + _CONTENT_W, _y(footer_top))
    _spaced(
        c, _MARGIN, footer_top + 14,
        "* Hash del documento firmado sin esta hoja de evidencia. La integridad del archivo completo "
        "la garantiza la firma digital PAdES incrustada.",
        _SANS, 7, _MUTED,
    )
    _spaced(c, _MARGIN, footer_top + 25, "Proyecto académico — sin validez jurídica.", _SANS, 7, _MUTED)

    c.showPage()
    c.save()
    return buf.getvalue()
