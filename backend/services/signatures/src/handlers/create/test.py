"""Unit tests for the signatures/create Lambda."""
from __future__ import annotations

import json
from uuid import uuid4
from unittest.mock import MagicMock


def _authed_event(body: dict) -> dict:
    return {
        "headers": {"Authorization": "Bearer tok", "Origin": "https://app.test"},
        "body": json.dumps(body),
    }


def _patch_auth(monkeypatch, user_id="u-1", email="u@x.co"):
    user = MagicMock(id=user_id, email=email, full_name="Fulano")
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(return_value=(user, MagicMock())),
    )
    return user


def test_signatures_create_happy_path_opens_ceremony(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    pid = uuid4()
    proc = MagicMock(id=pid, user_id=user.id, stage="signature", bank_id=1, form_snapshot=None,
                     amount=1000000, term_days=180, rate=12.5)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
    monkeypatch.setattr(
        h,
        "Signatures",
        MagicMock(
            get_active_for_process=MagicMock(return_value=None),
            create=MagicMock(return_value=MagicMock(
                public_dict=MagicMock(return_value={"token": "abc"})
            )),
        ),
    )
    monkeypatch.setattr(
        h,
        "Banks",
        MagicMock(get_by_id=MagicMock(return_value=MagicMock(name="Bancolombia"))),
    )
    monkeypatch.setattr(
        h,
        "Forms",
        MagicMock(get_by_user=MagicMock(return_value=MagicMock(
            public_dict=MagicMock(return_value={"full_name": "Fulano de Tal"})
        ))),
    )
    monkeypatch.setattr(h, "build_investment_order", MagicMock(return_value=b"%PDF-fake"))
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock())
    monkeypatch.setattr(h, "presign_download", MagicMock(return_value="https://s3.test/pdf"))
    monkeypatch.setattr(h, "send_email", MagicMock(return_value=True))
    monkeypatch.setattr(h, "_frontend_url", MagicMock(return_value="https://app.test"))

    resp = h.handler(_authed_event({"process_id": str(pid)}), None)

    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["signature"] == {"token": "abc"}
    # The exact URL path segment (e.g. `/sign/` vs `/#/firmar/`) belongs to
    # the frontend contract, not to this handler; assert only the invariants
    # we do own: base URL + trailing token.
    assert body["sign_url"].startswith("https://app.test/")
    assert body["pdf_url"] == "https://s3.test/pdf"
    assert body["emailed"] is True
    h.Signatures.create.assert_called_once()
    h.upload_from_bytes.assert_called_once()


def test_signatures_create_wrong_stage_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    proc = MagicMock(id=uuid4(), user_id=user.id, stage="form")
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
    # None of these should be reached.
    monkeypatch.setattr(h, "Signatures", MagicMock(get_active_for_process=MagicMock(side_effect=AssertionError)))
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))

    resp = h.handler(_authed_event({"process_id": str(uuid4())}), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "process_not_in_signature_stage"}


def test_signatures_create_reuses_active_ceremony(load_handler, monkeypatch):
    """Calling twice on the same process must return the same in-flight
    ceremony rather than stacking a new one."""
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    pid = uuid4()
    proc = MagicMock(id=pid, user_id=user.id, stage="signature")
    existing = MagicMock(
        stage="pending",
        token="existing-token",
        public_dict=MagicMock(return_value={"token": "existing-token"}),
    )
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
    monkeypatch.setattr(
        h,
        "Signatures",
        MagicMock(
            get_active_for_process=MagicMock(return_value=existing),
            create=MagicMock(side_effect=AssertionError("should reuse, not create")),
        ),
    )
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "_frontend_url", MagicMock(return_value="https://app.test"))

    resp = h.handler(_authed_event({"process_id": str(pid)}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["reused"] is True
    assert body["signature"] == {"token": "existing-token"}
    # Same rationale as the happy path: the concrete `/sign/` vs `/#/firmar/`
    # segment is a frontend concern.
    assert body["sign_url"].startswith("https://app.test/")
    assert body["sign_url"].endswith("existing-token")
