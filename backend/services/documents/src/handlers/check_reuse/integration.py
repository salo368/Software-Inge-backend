"""Deploy-verification test for documents/check_reuse.

Deliberately scoped to the negative case only: a throwaway user has no
prior validado id_front anywhere, so `reutilizable` must come back False.
A positive-case test (a real vigente document to offer) would need a
validado row to already exist, which today only comes from the on_upload
worker's happy path -- and that path depends on real OCR, which is not
yet available in the deployed Lambda (no `tesseract` binary packaged,
see services/documents/domain/adapters/tesseract_adapter.py). Once that
gap is closed, add a second test here that chains off a real validado
upload instead of inventing one directly in Postgres (inserting a
'validado' row by hand would test the query, not the real guarantee that
a validado row only exists because the worker actually validated it).

Gated by --integration (see backend/conftest.py).
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_documents import documents_api, insert_process_directly, pick_active_bank_id
from tests.integration_helpers import bearer, cleanup_process, cleanup_user, create_test_user_directly

pytestmark = pytest.mark.integration


def test_check_reuse_sin_documento_previo_no_es_reutilizable():
    session = create_test_user_directly()
    email = session["email"]
    process_id: str | None = None

    try:
        bank_id = pick_active_bank_id()
        process_id = insert_process_directly(user_id=session["user_id"], bank_id=bank_id)

        resp = requests.get(
            f"{documents_api()}/documents/check-reuse",
            headers=bearer(session["token"]),
            params={"process_id": process_id, "document_type": "id_front"},
            timeout=15,
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reutilizable"] is False
        assert "documento" not in body or body.get("documento") is None
    finally:
        if process_id:
            cleanup_process(process_id)
        cleanup_user(email)


def test_check_reuse_requiere_autenticacion():
    resp = requests.get(
        f"{documents_api()}/documents/check-reuse",
        params={"process_id": "00000000-0000-0000-0000-000000000000", "document_type": "id_front"},
        timeout=15,
    )
    assert resp.status_code == 401, resp.text
