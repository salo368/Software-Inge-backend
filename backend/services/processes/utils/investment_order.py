"""Renders the investment-order PDF the client signs.

Owned by `processes` (this is CDT-specific business logic; the
`signatures` service is deliberately generic and knows nothing about
orders, banks or terms). The output is a single-page PDF; `processes`
uploads it to `files`, gets a presigned URL back, then hands that URL
+ `SIGNATURE_LOCATION` to `signatures.create` to open the ceremony.

Layout is hand-placed rather than built with Platypus flowables: the
signature box has to land on an exact spot so the drawing stamp step in
the signatures service can drop the signer's drawing onto it, and
`SIGNATURE_LOCATION` below is the contract between the two.
Coordinates inside this module are PDF-style (origin bottom-left);
`SIGNATURE_LOCATION` is percentage from the top-left because that is
what the frontend preview and the signatures service both use.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as pdf_canvas

PAGE_W, PAGE_H = letter
MARGIN = 46
CONTENT_W = PAGE_W - 2 * MARGIN

BRAND = HexColor("#7c3aed")
BRAND_DARK = HexColor("#6d28d9")
BRAND_DEEPER = HexColor("#4c1d95")
INK = HexColor("#17143a")
MUTED = HexColor("#6b7280")
LINE = HexColor("#e5e1f5")
TINT = HexColor("#faf9fe")
POSITIVE = HexColor("#059669")
POSITIVE_TINT = HexColor("#ecfdf5")
WHITE = HexColor("#ffffff")

# Where the drawn signature gets stamped, as percentages of the page
# from the top-left. This is the SAME shape the signatures service
# expects in its `signature_location` field, so `processes` can pass
# it straight through when calling `POST /signatures`.
#
# Match with `_signature_block` below: if you move the on-page rule,
# also move this dict (otherwise the drawing lands somewhere else than
# the printed underline).
SIGNATURE_LOCATION: dict = {
    "page": 1,
    "x_pct": 9.0,
    "y_pct": 87.5,
    "width_pct": 28.0,
}

ROW_H = 19


def _money(value) -> str:
    return "$" + f"{float(value):,.0f}".replace(",", ".")


def _pct(value) -> str:
    return f"{float(value):.2f}".replace(".", ",") + "%"


def _date(value: date | datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%d/%m/%Y")


def maturity_value(amount: Decimal, rate: Decimal, term_days: int) -> tuple[float, float]:
    """Compound EA over a 365-day base, same formula the simulator shows."""
    factor = (1 + float(rate) / 100) ** (term_days / 365) - 1
    interest = round(float(amount) * factor)
    return interest, float(amount) + interest


def gradient_band(c, bottom: float, height: float) -> None:
    """linearGradient floods the whole canvas, so it has to run inside a clip."""
    c.saveState()
    path = c.beginPath()
    path.rect(0, bottom, PAGE_W, height)
    c.clipPath(path, stroke=0, fill=0)
    c.linearGradient(0, bottom, PAGE_W, bottom + height,
                     (BRAND_DEEPER, BRAND, BRAND_DARK), extend=True)
    # Subtle bubbles so the band does not read as a flat block.
    c.setFillColor(Color(1, 1, 1, alpha=0.09))
    c.circle(PAGE_W - 70, bottom + height - 18, 58, stroke=0, fill=1)
    c.circle(PAGE_W - 168, bottom + 6, 30, stroke=0, fill=1)
    c.restoreState()


def _header(c, order_number: str, issued_at: datetime) -> None:
    band_h = 104
    top = PAGE_H - band_h
    gradient_band(c, top, band_h)

    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 23)
    c.drawString(MARGIN, PAGE_H - 46, "CDTs")
    c.setFont("Helvetica-Bold", 10.5)
    c.setFillColor(Color(1, 1, 1, alpha=0.85))
    c.drawString(MARGIN, PAGE_H - 64, "ORDEN DE INVERSIÓN A TÉRMINO FIJO")

    c.setFont("Helvetica", 8.5)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 40, f"Orden N.° {order_number}")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 54, f"Emitida {_date(issued_at)}")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 68, issued_at.strftime("%H:%M UTC"))


def _hero(c, y: float, bank_name: str, amount, interest: float, final_amount: float) -> float:
    h = 90
    c.setFillColor(TINT)
    c.setStrokeColor(LINE)
    c.roundRect(MARGIN, y - h, CONTENT_W, h, 12, stroke=1, fill=1)

    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN + 20, y - 24, "MONTO A INVERTIR")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(MARGIN + 20, y - 51, _money(amount))
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN + 20, y - 70, f"Entidad receptora: {bank_name}")

    # Right-hand pill with the payoff, the number the client actually cares about.
    pill_w, pill_h = 214, 66
    pill_x = PAGE_W - MARGIN - 18 - pill_w
    pill_y = y - h + 12
    c.setFillColor(POSITIVE_TINT)
    c.setStrokeColor(HexColor("#a7f3d0"))
    c.roundRect(pill_x, pill_y, pill_w, pill_h, 10, stroke=1, fill=1)

    c.setFillColor(POSITIVE)
    c.setFont("Helvetica", 8)
    c.drawString(pill_x + 16, pill_y + 48, "RECIBIRÁS AL VENCIMIENTO")
    c.setFont("Helvetica-Bold", 19)
    c.drawString(pill_x + 16, pill_y + 25, _money(final_amount))
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(pill_x + 16, pill_y + 11, f"Rendimiento estimado +{_money(interest)}")
    return y - h - 20


def _section_title(c, y: float, text: str) -> float:
    c.setFillColor(BRAND)
    c.rect(MARGIN, y - 9, 3, 12, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(MARGIN + 11, y - 8, text)
    return y - 22


def _ellipsize(c, text: str, font: str, size: float, max_w: float) -> str:
    if c.stringWidth(text, font, size) <= max_w:
        return text
    while text and c.stringWidth(text + "…", font, size) > max_w:
        text = text[:-1]
    return text + "…"


def _rows(c, y: float, rows: list[tuple[str, str]], columns: int = 2) -> float:
    """Zebra-striped label/value grid. Returns the y below the block."""
    col_w = CONTENT_W / columns
    total_rows = (len(rows) + columns - 1) // columns

    for r in range(total_rows):
        row_y = y - (r + 1) * ROW_H
        if r % 2 == 0:
            c.setFillColor(TINT)
            c.rect(MARGIN, row_y, CONTENT_W, ROW_H, stroke=0, fill=1)
        for col in range(columns):
            idx = r * columns + col
            if idx >= len(rows):
                break
            label, value = rows[idx]
            x = MARGIN + col * col_w + 12
            right = MARGIN + (col + 1) * col_w - 12
            label = label.upper()
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 8)
            c.drawString(x, row_y + 6.5, label)
            available = right - x - c.stringWidth(label, "Helvetica", 8) - 10
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 8.6)
            c.drawRightString(right, row_y + 6.5,
                              _ellipsize(c, value, "Helvetica-Bold", 8.6, available))

    bottom = y - total_rows * ROW_H
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.rect(MARGIN, bottom, CONTENT_W, total_rows * ROW_H, stroke=1, fill=0)
    return bottom - 18


def _legal(c, y: float, lines: list[str]) -> float:
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.2)
    for line in lines:
        c.drawString(MARGIN, y, line)
        y -= 9.6
    return y


def _signature_block(c, holder_name: str, document: str) -> None:
    rule_y = PAGE_H * (1 - SIGNATURE_LOCATION["y_pct"] / 100)
    rule_x = PAGE_W * SIGNATURE_LOCATION["x_pct"] / 100
    rule_w = PAGE_W * SIGNATURE_LOCATION["width_pct"] / 100

    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    c.line(rule_x, rule_y, rule_x + rule_w, rule_y)

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(rule_x, rule_y - 13, holder_name)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.8)
    c.drawString(rule_x, rule_y - 24, document)
    c.drawString(rule_x, rule_y - 34, "Firma del titular")

    # Validity note balancing the right-hand side of the signature row.
    box_x = PAGE_W - MARGIN - 250
    c.setFillColor(TINT)
    c.setStrokeColor(LINE)
    c.roundRect(box_x, rule_y - 38, 250, 54, 8, stroke=1, fill=1)
    c.setFillColor(BRAND_DEEPER)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(box_x + 12, rule_y + 2, "FIRMA ELECTRÓNICA")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.4)
    c.drawString(box_x + 12, rule_y - 10, "Este documento se firma electrónicamente con")
    c.drawString(box_x + 12, rule_y - 19, "validación de identidad y código de un solo uso.")
    c.drawString(box_x + 12, rule_y - 28, "El certificado de firma se anexa al final.")


def _footer(c, order_number: str) -> None:
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(MARGIN, 44, PAGE_W - MARGIN, 44)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(MARGIN, 32, "CDTs — Plataforma de depósitos a término fijo")
    c.drawRightString(PAGE_W - MARGIN, 32, f"Orden {order_number} · Página 1 de 1")


def build_investment_order(*, process, form, user, bank_name: str) -> bytes:
    """`form` may be None if the snapshot is missing; the doc degrades to dashes."""
    issued_at = datetime.now(timezone.utc)
    order_number = str(process.id)[:8].upper()
    interest, final_amount = maturity_value(process.amount, process.rate, process.term_days)
    maturity_date = issued_at.date() + timedelta(days=process.term_days)
    snapshot = form or {}

    def field(key: str, default: str = "-") -> str:
        value = snapshot.get(key)
        return default if value in (None, "") else str(value)

    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"Orden de inversión {order_number}")

    _header(c, order_number, issued_at)

    y = PAGE_H - 104 - 24
    y = _hero(c, y, bank_name, process.amount, interest, final_amount)

    y = _section_title(c, y, "Condiciones de la inversión")
    y = _rows(c, y, [
        ("Entidad", bank_name),
        ("Plazo", f"{process.term_days} días"),
        ("Tasa efectiva anual", _pct(process.rate)),
        ("Modalidad", "Interés compuesto, base 365"),
        ("Fecha de apertura", _date(issued_at)),
        ("Fecha de vencimiento", _date(maturity_date)),
        ("Capital", _money(process.amount)),
        ("Rendimiento estimado", _money(interest)),
    ])

    y = _section_title(c, y, "Datos del titular")
    y = _rows(c, y, [
        ("Nombre completo", field("full_name", user.full_name)),
        ("Documento", f"{field('document_type')} {field('document_number')}"),
        ("Fecha de nacimiento", field("birth_date")),
        ("Correo electrónico", user.email),
        ("Teléfono", field("phone")),
        ("Ciudad", field("city")),
        ("Dirección", field("address")),
        ("Ocupación", field("occupation")),
    ])

    y = _section_title(c, y, "Perfil financiero declarado")
    income = snapshot.get("monthly_income")
    expenses = snapshot.get("monthly_expenses")
    assets = snapshot.get("total_assets")
    liabilities = snapshot.get("total_liabilities")
    equity = None
    if assets is not None and liabilities is not None:
        equity = float(assets) - float(liabilities)
    y = _rows(c, y, [
        ("Ingresos mensuales", _money(income) if income is not None else "-"),
        ("Egresos mensuales", _money(expenses) if expenses is not None else "-"),
        ("Total activos", _money(assets) if assets is not None else "-"),
        ("Total pasivos", _money(liabilities) if liabilities is not None else "-"),
        ("Patrimonio", _money(equity) if equity is not None else "-"),
        ("Actividad económica", field("economic_activity")),
        ("Origen de los fondos", field("source_of_funds")),
        ("Persona expuesta (PEP)", "Sí" if snapshot.get("is_peps") else "No"),
    ])

    _legal(c, y, [
        "El titular declara que los recursos objeto de esta orden provienen de actividades lícitas y que la información aquí",
        "consignada es veraz, completa y verificable. Acepta las condiciones del depósito a término fijo: el capital permanecerá",
        f"invertido durante {process.term_days} días y los rendimientos se liquidarán al vencimiento a la tasa del {_pct(process.rate)} efectiva anual.",
        "La cancelación anticipada está sujeta a las políticas de la entidad receptora y puede implicar la pérdida de rendimientos.",
        "Los valores de rendimiento son estimados y no incluyen la retención en la fuente aplicable.",
    ])

    _signature_block(
        c,
        field("full_name", user.full_name),
        f"{field('document_type')} {field('document_number')}",
    )
    _footer(c, order_number)

    c.showPage()
    c.save()
    return buf.getvalue()
