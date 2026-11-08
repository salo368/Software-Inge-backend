
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as pdf_canvas

_PAGE_W, _PAGE_H = 612.0, 792.0
_FONT = "Helvetica"
_FONT_SIZE = 9

_FIELD_XY = {
    "name": (49.8, 134.2),
    "second_name": (181.4, 134.2),
    "last_name": (313.0, 134.2),
    "second_last_name": (444.6, 134.2),
    "document_type": (49.8, 178.4),
    "document_number": (181.4, 178.4),
    "nationality": (313.0, 178.4),
    "gender": (444.6, 178.4),
    "document_issuance_date": (49.8, 222.6),
    "document_issuance_country": (181.4, 222.6),
    "document_issuance_department": (313.0, 222.6),
    "document_issuance_city": (444.6, 222.6),
    "birth_date": (49.8, 266.9),
    "birth_country": (181.4, 266.9),
    "birth_department": (313.0, 266.9),
    "birth_city": (444.6, 266.9),
    "civil_status": (49.8, 311.1),
    "education_level": (181.4, 311.1),
    "phone_ext": (313.0, 311.1),
    "phone_number": (444.6, 311.1),
    "email": (49.8, 355.3),
    "monthly_income": (49.8, 435.0),
    "monthly_expenses": (181.4, 435.0),
    "total_assets": (313.0, 435.0),
    "total_liabilities": (444.6, 435.0),
    "amount": (49.8, 558.8),
    "term": (181.4, 558.8),
    "rate": (313.0, 558.8),
    "opening_date": (444.6, 558.8),
    "document_number_footer": (313.0, 724.1),
}
_VALUE_Y_OFFSET = 14.0  # points below the label's bottom edge

# Checkbox centers (top-origin points) for the two Si/No questions.
_TAX_DECLARANT_YES = (54.7, 489.5)
_TAX_DECLARANT_NO = (91.6, 489.5)
_PEP_YES = (317.9, 489.5)
_PEP_NO = (354.8, 489.5)


SIGNATURE_LOCATION = [{
    "page": 1,
    "x_pct": 8.0,
    "y_pct": 80.0,
    "width_pct": 40.0,
    "height_pct": 14.0,
}]


def _to_pdf_y(y_top_origin: float) -> float:
    return _PAGE_H - y_top_origin


def _text(value) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _money(value) -> str:
    if value is None:
        return "-"
    try:
        return f"$ {Decimal(str(value)):,.0f}"
    except InvalidOperation:
        return "-"


def populate_investment_order(
    template_pdf: bytes,
    *,
    form: dict,
    amount,
    term: int,
    rate,
) -> bytes:
   
    form = form or {}

    values = {
        "name": _text(form.get("name")),
        "second_name": _text(form.get("second_name")),
        "last_name": _text(form.get("last_name")),
        "second_last_name": _text(form.get("second_last_name")),
        "document_type": _text(form.get("document_type")),
        "document_number": _text(form.get("document_number")),
        "nationality": _text(form.get("nationality")),
        "gender": _text(form.get("gender")),
        "document_issuance_date": _text(form.get("document_issuance_date")),
        "document_issuance_country": _text(form.get("document_issuance_country")),
        "document_issuance_department": _text(form.get("document_issuance_department")),
        "document_issuance_city": _text(form.get("document_issuance_city")),
        "birth_date": _text(form.get("birth_date")),
        "birth_country": _text(form.get("birth_country")),
        "birth_department": _text(form.get("birth_department")),
        "birth_city": _text(form.get("birth_city")),
        "civil_status": _text(form.get("civil_status")),
        "education_level": _text(form.get("education_level")),
        "phone_ext": _text(form.get("phone_ext")),
        "phone_number": _text(form.get("phone_number")),
        "email": _text(form.get("email")),
        "monthly_income": _money(form.get("monthly_income")),
        "monthly_expenses": _money(form.get("monthly_expenses")),
        "total_assets": _money(form.get("total_assets")),
        "total_liabilities": _money(form.get("total_liabilities")),
        "amount": _money(amount),
        "term": f"{term} dias",
        "rate": f"{Decimal(str(rate)):.2f}% E.A.",
        "opening_date": datetime.now().strftime("%d/%m/%Y"),
        "document_number_footer": _text(form.get("document_number")),
    }

    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(_PAGE_W, _PAGE_H))
    c.setFont(_FONT, _FONT_SIZE)

    for field, value in values.items():
        x, label_bottom = _FIELD_XY[field]
        c.drawString(x, _to_pdf_y(label_bottom + _VALUE_Y_OFFSET), value)

    def _mark_checkbox(center):
        cx, cy = center
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(cx, _to_pdf_y(cy) - 3.5, "X")
        c.setFont(_FONT, _FONT_SIZE)

    _mark_checkbox(_TAX_DECLARANT_YES if form.get("is_tax_declarant") else _TAX_DECLARANT_NO)
    _mark_checkbox(_PEP_YES if form.get("is_pep") else _PEP_NO)

    c.save()

    overlay_reader = PdfReader(BytesIO(buf.getvalue()))
    template_reader = PdfReader(BytesIO(template_pdf))
    template_reader.pages[0].merge_page(overlay_reader.pages[0])

    writer = PdfWriter()
    writer.append(template_reader)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()
