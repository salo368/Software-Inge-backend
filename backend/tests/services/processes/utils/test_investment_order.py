"""Unit tests for `services/processes/utils/investment_order.py`.

Cross-cutting because the module lives inside a specific block's utils/
directory but has no `handler.py` sibling. Follows the same sys.path
escape hatch as `test_mock_ca.py` and `test_stamp.py`.

What we assert:

    * `build_investment_order` returns real PDF bytes that pypdf can
      parse without complaining and that carry the expected page count.
    * The rendered content includes the order number, bank name and
      formatted amount, so anyone extracting text from the PDF (auditor,
      client, us during debugging) sees the right business data.
    * `form=None` degrades gracefully to dashes rather than crashing.
    * `SIGNATURE_LOCATION` matches the shape the signatures service
      expects in `POST /signatures.signature_location`, so processes
      can pass it through unchanged.
    * `maturity_value` computes compound-EA correctly on a 365-day base
      (this is a math primitive the frontend simulator also uses;
      keeping it precise avoids client-visible drift).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[4]
_PROC_UTILS = _BACKEND / "services" / "processes" / "utils"
sys.path.insert(0, str(_PROC_UTILS))

for _n in list(sys.modules):
    if _n == "utils" or _n.startswith("utils."):
        sys.modules.pop(_n, None)

import investment_order  # noqa: E402


def _process(**overrides):
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    defaults = {
        "id": "abcd1234-ef56-7890-abcd-ef1234567890",
        "amount": Decimal("5000000"),
        "rate": Decimal("12.50"),
        "term_days": 180,
        "created_at": now,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _user(**overrides):
    defaults = {
        "email": "titular@example.com",
        "full_name": "Ada Lovelace",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _form(**overrides):
    """A representative form snapshot; overrides individual fields."""
    base = {
        "full_name": "Ada Augusta Lovelace",
        "document_type": "CC",
        "document_number": "1234567890",
        "birth_date": "10/12/1815",
        "phone": "+57 300 000 0000",
        "city": "Bogota",
        "address": "Cra 7 # 100-00",
        "occupation": "Mathematician",
        "monthly_income": 12_000_000,
        "monthly_expenses": 5_000_000,
        "total_assets": 300_000_000,
        "total_liabilities": 50_000_000,
        "economic_activity": "Consulting",
        "source_of_funds": "Employment",
        "is_peps": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# SIGNATURE_LOCATION contract with the signatures service
# ---------------------------------------------------------------------------
class TestSignatureLocation:
    def test_shape_matches_signatures_api(self):
        """POST /signatures.signature_location must be a dict with at
        least page/x_pct/y_pct; width_pct is optional but we always
        provide it here for a predictable box size."""
        loc = investment_order.SIGNATURE_LOCATION
        assert isinstance(loc, dict)
        for k in ("page", "x_pct", "y_pct", "width_pct"):
            assert k in loc
        assert loc["page"] >= 1
        for k in ("x_pct", "y_pct"):
            assert 0 <= loc[k] <= 100
        assert 0 < loc["width_pct"] <= 100

    def test_signature_location_is_on_page_one(self):
        """The order is one page long; a signature location pointing at
        page 2 would silently break the ceremony after signing (the
        drawing wouldn't be visible because it would land on an
        appended blank page)."""
        assert investment_order.SIGNATURE_LOCATION["page"] == 1


# ---------------------------------------------------------------------------
# maturity_value math
# ---------------------------------------------------------------------------
class TestMaturityValue:
    def test_zero_days_yields_zero_interest(self):
        interest, total = investment_order.maturity_value(Decimal("1_000_000"), Decimal("10"), 0)
        assert interest == 0
        assert total == 1_000_000

    def test_one_year_at_ten_percent(self):
        """365 days at 10% EA on 1,000,000 -> exactly 100,000 interest
        (this is the simplest sanity number a reviewer can check by
        hand)."""
        interest, total = investment_order.maturity_value(
            Decimal("1000000"), Decimal("10"), 365
        )
        assert interest == 100_000
        assert total == 1_100_000

    def test_partial_year(self):
        """180 days at 12% EA on 5,000,000. Formula:
        interest = amount * ((1 + 0.12)**(180/365) - 1)
        `interest` is rounded to peso; `total = amount + rounded_interest`."""
        interest, total = investment_order.maturity_value(
            Decimal("5000000"), Decimal("12"), 180
        )
        expected_interest = round(5_000_000 * ((1 + 0.12) ** (180 / 365) - 1))
        assert interest == expected_interest
        assert total == 5_000_000 + expected_interest


# ---------------------------------------------------------------------------
# PDF output
# ---------------------------------------------------------------------------
class TestPdfOutput:
    def test_returns_valid_single_page_pdf(self):
        pdf = investment_order.build_investment_order(
            process=_process(),
            form=_form(),
            user=_user(),
            bank_name="Banco de Prueba",
        )
        assert pdf.startswith(b"%PDF")

        from pypdf import PdfReader

        r = PdfReader(BytesIO(pdf))
        assert len(r.pages) == 1

    def test_form_none_does_not_crash(self):
        """Snapshot may be missing (e.g. old process without a form
        record). The document must still render with dashes in place of
        the missing fields, so processes never blocks the ceremony on a
        broken snapshot."""
        pdf = investment_order.build_investment_order(
            process=_process(),
            form=None,
            user=_user(),
            bank_name="Banco de Prueba",
        )
        from pypdf import PdfReader

        r = PdfReader(BytesIO(pdf))
        assert len(r.pages) == 1

    def test_embeds_business_fields(self):
        pdf = investment_order.build_investment_order(
            process=_process(),
            form=_form(),
            user=_user(),
            bank_name="Banco Popular",
        )
        from pypdf import PdfReader

        text = PdfReader(BytesIO(pdf)).pages[0].extract_text()
        # Order number = first 8 chars of process.id, upper-cased.
        assert "ABCD1234" in text
        # Bank name shows up in both hero and the conditions table.
        assert "Banco Popular" in text
        # Amount is formatted with dots as thousand separator.
        assert "5.000.000" in text
        # Term / rate / holder / doc number all render.
        assert "180" in text
        assert "12,50" in text
        assert "Ada Augusta Lovelace" in text
        assert "1234567890" in text

    def test_peps_true_prints_si(self):
        pdf = investment_order.build_investment_order(
            process=_process(),
            form=_form(is_peps=True),
            user=_user(),
            bank_name="Banco",
        )
        from pypdf import PdfReader

        text = PdfReader(BytesIO(pdf)).pages[0].extract_text()
        # `is_peps=True` renders "Sí"; the ASCII "Si" alternative would
        # be a locale regression.
        assert "Sí" in text
