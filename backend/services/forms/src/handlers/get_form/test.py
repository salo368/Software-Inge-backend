"""Unit tests for the forms/get_form Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _authed_event() -> dict:
    return {"headers": {"Authorization": "Bearer tok"}}


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.UserBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user)))
    return user


def _fake_form_row(**overrides):
    # `name` is a reserved MagicMock constructor kwarg (sets its repr, not
    # a `.name` attribute), so build it empty and assign attributes after.
    defaults = dict(
        name="FOO",
        second_name="MIDDLE",
        last_name="BAR",
        second_last_name="BAZ",
        gender="M",
        birth_date=datetime(1990, 5, 1, tzinfo=timezone.utc),
        birth_country="COLOMBIA",
        birth_department="QUINDIO",
        birth_city="ARMENIA",
        nationality="COLOMBIA",
        email="foo@example.com",
        document_type="CC",
        document_number="123456789",
        document_issuance_date=datetime(2010, 1, 1, tzinfo=timezone.utc),
        document_issuance_country="COLOMBIA",
        document_issuance_department="CUNDINAMARCA",
        document_issuance_city="BOGOTA_DC",
        phone_ext="57",
        phone_number="3000000000",
        civil_status="SINGLE",
        education_level="PROFESSIONAL",
        is_pep=False,
        monthly_income=1000.0,
        monthly_expenses=500.0,
        total_assets=5000.0,
        total_liabilities=0.0,
        is_tax_declarant=True,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    row = MagicMock()
    for key, value in defaults.items():
        setattr(row, key, value)
    return row


def test_get_form_returns_form_when_present(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    monkeypatch.setattr(h, "Forms", MagicMock(get_by_user_id=MagicMock(return_value=_fake_form_row())))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    form = json.loads(resp["body"])["form"]
    assert form["name"] == "FOO"
    assert form["document_type"] == "CC"
    assert form["birth_date"] == "01/05/1990"
    assert form["document_issuance_date"] == "01/01/2010"
    assert form["updated_at"] == "2026-01-01 00:00:00+00:00"
    h.Forms.get_by_user_id.assert_called_once_with(user.id)


def test_get_form_returns_null_when_no_form(load_handler, monkeypatch):
    """A user without a filled form gets `null` instead of a 404 so the SPA
    can tell 'not filled yet' from 'error'."""
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(get_by_user_id=MagicMock(return_value=None)))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"form": None}


def test_get_form_missing_bearer_returns_401(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Forms", MagicMock(get_by_user_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}
