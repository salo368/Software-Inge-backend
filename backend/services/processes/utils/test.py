"""Unit tests for the processes-block-local `investment_order` util.

Imported by its own file path (not as `utils.investment_order`) so this
test is self-contained and does not depend on conftest.py's block-local
`utils`/`data` namespace-package binding, which is wired for handler.py
siblings loaded via the `load_handler` fixture, not for a bare module
test like this one.
"""
from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as pdf_canvas

_MODULE_PATH = Path(__file__).resolve().parent / "investment_order.py"
_spec = importlib.util.spec_from_file_location("investment_order", _MODULE_PATH)
investment_order = importlib.util.module_from_spec(_spec)
sys.modules["investment_order"] = investment_order
_spec.loader.exec_module(investment_order)

populate_investment_order = investment_order.populate_investment_order
SIGNATURE_LOCATION = investment_order.SIGNATURE_LOCATION


def _blank_letter_pdf() -> bytes:
    """A single blank 612x792 page -- stands in for a bank's io_key
    template; the overlay logic under test doesn't care what (if
    anything) was already on the page."""
    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(612, 792))
    c.showPage()
    c.save()
    return buf.getvalue()


_FORM = {
    "name": "Ana", "second_name": "Maria", "last_name": "Gomez", "second_last_name": "Ruiz",
    "document_type": "CC", "document_number": "123456789", "nationality": "Colombiana",
    "gender": "F", "document_issuance_date": "01/01/2020", "document_issuance_country": "Colombia",
    "document_issuance_department": "Cundinamarca", "document_issuance_city": "Bogota",
    "birth_date": "02/02/1990", "birth_country": "Colombia", "birth_department": "Antioquia",
    "birth_city": "Medellin", "civil_status": "SINGLE", "education_level": "PROFESSIONAL",
    "phone_ext": "57", "phone_number": "3001234567", "email": "ana@example.com",
    "monthly_income": 5000000, "monthly_expenses": 2000000, "total_assets": 100000000,
    "total_liabilities": 10000000, "is_tax_declarant": True, "is_pep": False,
}


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return reader.pages[0].extract_text()


def test_populate_investment_order_renders_all_form_fields():
    out = populate_investment_order(
        _blank_letter_pdf(), form=_FORM, amount=Decimal("12000000"), term=365, rate=Decimal("12.5"),
    )

    text = _extract_text(out)
    for expected in [
        "Ana", "Maria", "Gomez", "Ruiz", "CC", "123456789", "Colombiana", "F",
        "01/01/2020", "Bogota", "02/02/1990", "Medellin", "SINGLE", "PROFESSIONAL",
        "57", "3001234567", "ana@example.com",
    ]:
        assert expected in text, f"{expected!r} missing from overlaid text"


def test_populate_investment_order_formats_money_and_commercial_terms():
    out = populate_investment_order(
        _blank_letter_pdf(), form=_FORM, amount=Decimal("12345678"), term=365, rate=Decimal("12.50"),
    )

    text = _extract_text(out)
    assert "$ 12,345,678" in text
    assert "365 dias" in text
    assert "12.50% E.A." in text
    # Monthly income etc. also go through the money formatter.
    assert "$ 5,000,000" in text


def test_populate_investment_order_missing_optional_fields_render_as_dash():
    form = dict(_FORM)
    form["second_name"] = None
    form["phone_ext"] = None

    out = populate_investment_order(
        _blank_letter_pdf(), form=form, amount=Decimal("1000000"), term=180, rate=Decimal("10"),
    )

    # Just needs to not crash and still produce a readable PDF -- a
    # missing field renders as "-" rather than blowing up str(None).
    text = _extract_text(out)
    assert "-" in text


def test_populate_investment_order_empty_form_does_not_raise():
    out = populate_investment_order(
        _blank_letter_pdf(), form={}, amount=Decimal("1000000"), term=180, rate=Decimal("10"),
    )

    reader = PdfReader(BytesIO(out))
    assert len(reader.pages) == 1


def test_populate_investment_order_tax_declarant_flag_changes_output():
    """is_tax_declarant / is_pep flip which checkbox gets marked -- the
    two outputs must differ even though every other field is identical."""
    form_yes = dict(_FORM, is_tax_declarant=True, is_pep=True)
    form_no = dict(_FORM, is_tax_declarant=False, is_pep=False)

    out_yes = populate_investment_order(
        _blank_letter_pdf(), form=form_yes, amount=Decimal("1000000"), term=180, rate=Decimal("10"),
    )
    out_no = populate_investment_order(
        _blank_letter_pdf(), form=form_no, amount=Decimal("1000000"), term=180, rate=Decimal("10"),
    )

    assert out_yes != out_no


def test_populate_investment_order_preserves_template_page_count():
    buf = BytesIO()
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(_blank_letter_pdf())))
    writer.append(PdfReader(BytesIO(_blank_letter_pdf())))
    writer.write(buf)
    two_page_template = buf.getvalue()

    out = populate_investment_order(
        two_page_template, form=_FORM, amount=Decimal("1000000"), term=180, rate=Decimal("10"),
    )

    assert len(PdfReader(BytesIO(out)).pages) == 2


def test_signature_location_targets_page_one():
    assert SIGNATURE_LOCATION[0]["page"] == 1
    assert 0 < SIGNATURE_LOCATION[0]["x_pct"] < 100
    assert 0 < SIGNATURE_LOCATION[0]["y_pct"] < 100
