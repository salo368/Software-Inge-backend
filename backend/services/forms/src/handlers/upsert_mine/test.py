"""Unit tests for the forms/upsert_mine Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _authed_event(body: dict) -> dict:
    return {"headers": {"Authorization": "Bearer tok"}, "body": json.dumps(body)}


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(return_value=(user, MagicMock())),
    )
    return user


def _valid_payload() -> dict:
    return {
        "full_name": "Foo Bar",
        "birth_date": "1990-05-01",
        "document_type": "cc",
        "document_number": "123",
        "phone": "3000000000",
        "address": "Calle 1",
        "city": "Bogota",
        "occupation": "dev",
        "economic_activity": "software",
        "source_of_funds": "salary",
        "monthly_income": "5000000",
        "monthly_expenses": "2000000",
        "total_assets": "10000000",
        "total_liabilities": "3000000",
        "is_peps": False,
    }


def test_upsert_mine_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    saved = MagicMock(public_dict=MagicMock(return_value={"full_name": "Foo Bar"}))
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(return_value=saved)))

    resp = h.handler(_authed_event(_valid_payload()), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"form": {"full_name": "Foo Bar"}}
    args, kwargs = h.Forms.upsert.call_args
    assert args[0] == user.id
    assert kwargs["document_type"] == "CC"  # uppercased


def test_upsert_mine_missing_required_field_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload()
    payload["full_name"] = ""

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "full_name is required"}


def test_upsert_mine_invalid_document_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload()
    payload["document_type"] = "XYZ"

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert "document_type must be one of" in json.loads(resp["body"])["error"]
