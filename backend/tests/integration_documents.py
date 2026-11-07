"""End-to-end helpers for `documents/**/integration.py`.

Mirrors the shape of `tests/integration_signatures.py` and the pattern
already proven in `services/files/src/handlers/get_upload_url/integration.py`:
block-local (seeds its own user and process directly in Postgres, reads an
active bank straight from the catalog table), so `documents` integration
tests never depend on `auth`/`banks`/`processes` being freshly deployed in
the same pipeline run.

Generating real JPEG bytes (`make_test_jpeg`) requires Pillow, already a
transitive dependency of `requirements-dev.txt` (used by the signatures
integration suite for the face fixture) and of `documents/requirements.txt`
itself (the real adapter uses it to open the image before handing it to
Tesseract).
"""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from tests.integration_helpers import STAGE, db_conn, query_scalar

DOCUMENTS_BUCKET = os.environ.get("DOCUMENTS_BUCKET", f"cdts-{STAGE}-documents")


def documents_api() -> str:
    from tests.integration_helpers import api_base

    return api_base("documents")


def pick_active_bank_id() -> int:
    """Same rationale as files' integration suite: banks is a static
    catalog, read it directly instead of calling /banks, so this suite
    does not depend on the banks block being freshly deployed."""
    bid = query_scalar("SELECT id FROM banks WHERE is_active = true ORDER BY id LIMIT 1")
    assert bid is not None, "no active banks in dev; seed the catalog before running this test"
    return int(bid)


def insert_form_directly(*, user_id: str, full_name: str) -> None:
    """The worker reads the declared name from `forms.full_name` to run
    `corresponde_con_declarado`. Without a forms row, nombre_declarado is
    '' and the happy path can never match, no matter how good the OCR is
    -- so the happy-path integration test needs this, the rejection-path
    one does not (it never reaches the name-matching step)."""
    now = datetime.now(timezone.utc)
    with db_conn() as c:
        c.run(
            "INSERT INTO forms (user_id, full_name, birth_date, document_type, "
            "document_number, phone, address, city, occupation, economic_activity, "
            "monthly_income, monthly_expenses, total_assets, total_liabilities, "
            "source_of_funds, is_peps, created_at, updated_at) "
            "VALUES (:uid, :name, :bd, :dt, :dn, :ph, :addr, :city, :occ, :ea, "
            ":mi, :me, :ta, :tl, :sf, :peps, :now, :now)",
            uid=uuid.UUID(user_id), name=full_name, bd="1990-01-01", dt="CC",
            dn="1000000000", ph="3000000000", addr="Calle Falsa 123", city="Bogota",
            occ="Integration Tester", ea="Tecnologia",
            mi=Decimal("5000000"), me=Decimal("1000000"),
            ta=Decimal("10000000"), tl=Decimal("0"), sf="Salario",
            peps=False, now=now,
        )


def insert_process_directly(*, user_id: str, bank_id: int) -> str:
    """Throwaway process in the 'documents' stage -- same helper shape as
    files' `_insert_process_directly`, duplicated rather than imported
    because block-local integration suites intentionally do not import
    from each other's `integration.py` (see docs/repo-structure.md §13.3:
    a cross-block call here would race against a sibling package that may
    not have deployed in this same run)."""
    pid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with db_conn() as c:
        c.run(
            "INSERT INTO processes "
            "(id, user_id, bank_id, amount, term_days, rate, stage, created_at) "
            "VALUES (:id, :uid, :bid, :amt, :term, :rate, :st, :now)",
            id=pid, uid=uuid.UUID(user_id), bid=bank_id,
            amt=Decimal("1000000"), term=180, rate=Decimal("12.5"),
            st="documents", now=now,
        )
    return str(pid)


def make_garbage_bytes(size: int = 2048) -> bytes:
    """FE1 fixture: plausible size, but not a JPEG/PNG signature at all.
    Deterministic -- does not depend on OCR or on any image library."""
    return b"not-an-image-" * (size // 14 + 1)


def make_test_jpeg(*, text: str, width: int = 600, height: int = 300) -> bytes:
    """FB fixture: a REAL JPEG (valid magic bytes, real encoded size) with
    `text` drawn in large black letters on a white background.

    Not a synthetic ExtractedFields like the unit tests use -- this is
    actual image bytes that get handed to the real OCR adapter in the
    deployed Lambda. Whether Tesseract can read it back correctly is
    exactly what the happy-path integration test is for; a blank/corporate
    font rendering is not a guarantee of real-world cédula legibility, but
    it is a real, reproducible OCR exercise, not a mock.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    draw.text((20, height // 2 - 20), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
