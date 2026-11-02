"""Unit tests for the signatures/set_signature_form Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4


def _row(stage, created_at, **overrides):
    defaults = dict(
        id=str(uuid4()),
        stage=stage,
        created_at=created_at,
        email=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _event(signature_id, email) -> dict:
    body = {}
    if signature_id is not None:
        body["signature_id"] = str(signature_id)
    if email is not None:
        body["email"] = email
    return {"body": json.dumps(body)}


def test_set_signature_form_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="FORM", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(h, "Signatures", MagicMock(
        get_by_id=MagicMock(return_value=row),
        set_email=MagicMock(return_value=_row(
            stage="BIOMETRICS", created_at=row.created_at, id=row.id, email="juan@example.com",
        )),
    ))

    resp = h.handler(_event(row.id, "  Juan@Example.com  "), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["id"] == row.id
    assert body["stage"] == "BIOMETRICS"
    assert body["email"] == "juan@example.com"

    h.Signatures.set_email.assert_called_once_with(UUID(row.id), "juan@example.com")


def test_set_signature_form_missing_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(None, "juan@example.com"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signature_id is required"}


def test_set_signature_form_invalid_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event("not-a-uuid", "juan@example.com"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid signature_id"}


def test_set_signature_form_invalid_email_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(uuid4(), "not-an-email"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_email"}


def test_set_signature_form_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    resp = h.handler(_event(uuid4(), "juan@example.com"), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "signature_not_found"}


def test_set_signature_form_past_signing_window_returns_410(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="FORM", created_at=datetime.now(timezone.utc) - timedelta(minutes=21))
    monkeypatch.setattr(h, "Signatures", MagicMock(
        get_by_id=MagicMock(return_value=row),
        set_email=MagicMock(side_effect=AssertionError),
    ))

    resp = h.handler(_event(row.id, "juan@example.com"), None)

    assert resp["statusCode"] == 410
    assert json.loads(resp["body"]) == {"error": "signature_expired"}


def test_set_signature_form_wrong_stage_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(h, "Signatures", MagicMock(
        get_by_id=MagicMock(return_value=row),
        set_email=MagicMock(side_effect=AssertionError),
    ))

    resp = h.handler(_event(row.id, "juan@example.com"), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "signature_not_in_form_stage"}
