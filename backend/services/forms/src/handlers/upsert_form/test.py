"""Unit tests for the forms/upsert_form Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def _authed_event(body: dict) -> dict:
    return {"headers": {"Authorization": "Bearer tok"}, "body": json.dumps(body)}


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user)))
    return user


def _fake_form_row(**overrides):
    # `name` is a reserved MagicMock constructor kwarg (sets its repr, not
    # a `.name` attribute), so build it empty and assign attributes after.
    defaults = dict(
        name="Foo",
        second_name="Middle",
        last_name="Bar",
        second_last_name="Baz",
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


def _valid_payload(**overrides) -> dict:
    payload = {
        "name": "Foo",
        "second_name": "Middle",
        "last_name": "Bar",
        "second_last_name": "Baz",
        "gender": "M",
        "birth_date": "1990-05-01",
        "birth_country": "COLOMBIA",
        "birth_department": "QUINDIO",
        "birth_city": "ARMENIA",
        "nationality": "COLOMBIA",
        "document_number": "123456789",
        "document_type": "CC",
        "email": "foo@example.com",
        "document_issuance_date": "2010-01-01",
        "document_issuance_country": "COLOMBIA",
        "document_issuance_department": "CUNDINAMARCA",
        "document_issuance_city": "BOGOTA_DC",
        "phone_ext": "57",
        "phone_number": "3000000000",
        "civil_status": "SINGLE",
        "education_level": "PROFESSIONAL",
        "is_pep": False,
        "monthly_income": 1000.0,
        "monthly_expenses": 500.0,
        "total_assets": 5000.0,
        "total_liabilities": 0.0,
        "is_tax_declarant": True,
    }
    payload.update(overrides)
    return payload


def test_upsert_form_happy_path_full_payload(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    saved = _fake_form_row()
    upsert_mock = MagicMock(return_value=saved)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=upsert_mock))

    resp = h.handler(_authed_event(_valid_payload()), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])["form"]
    assert body["name"] == "Foo"
    assert body["birth_date"] == "1990-05-01 00:00:00+00:00"
    assert body["is_pep"] is False
    assert body["monthly_income"] == 1000.0

    args, kwargs = upsert_mock.call_args
    assert args[0] == user.id
    assert kwargs["birth_date"] == datetime(1990, 5, 1, tzinfo=timezone.utc)
    assert kwargs["birth_country"] == "COLOMBIA"
    assert kwargs["is_pep"] is False


def test_upsert_form_uppercases_the_four_name_fields(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    saved = _fake_form_row()
    upsert_mock = MagicMock(return_value=saved)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=upsert_mock))

    payload = _valid_payload(
        name="foo", second_name="miDDle", last_name="Bar", second_last_name="baZ"
    )

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 200
    _, kwargs = upsert_mock.call_args
    assert kwargs["name"] == "FOO"
    assert kwargs["second_name"] == "MIDDLE"
    assert kwargs["last_name"] == "BAR"
    assert kwargs["second_last_name"] == "BAZ"


def test_upsert_form_only_second_name_parts_are_optional(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    saved = _fake_form_row()
    upsert_mock = MagicMock(return_value=saved)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=upsert_mock))

    payload = _valid_payload()
    del payload["second_name"]
    del payload["second_last_name"]

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 200
    _, kwargs = upsert_mock.call_args
    assert kwargs["second_name"] is None
    assert kwargs["second_last_name"] is None


@pytest.mark.parametrize(
    "field, expected_error",
    [
        ("gender", "gender is required"),
        ("birth_date", "birth_date is required"),
        ("birth_country", "birth_country is required"),
        ("birth_department", "birth_department is required"),
        ("birth_city", "birth_city is required"),
        ("nationality", "nationality is required"),
        ("document_issuance_date", "document_issuance_date is required"),
        ("document_issuance_country", "document_issuance_country is required"),
        ("document_issuance_department", "document_issuance_department is required"),
        ("document_issuance_city", "document_issuance_city is required"),
        ("phone_ext", "phone_ext is required"),
        ("phone_number", "phone_number is required"),
        ("civil_status", "civil_status is required"),
        ("education_level", "education_level is required"),
        ("is_pep", "is_pep is required"),
        ("monthly_income", "monthly_income is required"),
        ("monthly_expenses", "monthly_expenses is required"),
        ("total_assets", "total_assets is required"),
        ("total_liabilities", "total_liabilities is required"),
        ("is_tax_declarant", "is_tax_declarant is required"),
    ],
)
def test_upsert_form_missing_now_required_field_returns_400(
    load_handler, monkeypatch, field, expected_error
):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload()
    del payload[field]

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": expected_error}


def test_upsert_form_missing_name_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload()
    del payload["name"]

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "name is required"}


def test_upsert_form_empty_name_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(name="")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "name must be a non-empty string"}


def test_upsert_form_invalid_document_number_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(document_number="abc123")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "document_number must be numeric"}


def test_upsert_form_invalid_document_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(document_type="XYZ")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert "document_type must be one of" in json.loads(resp["body"])["error"]


def test_upsert_form_invalid_email_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(email="not-an-email")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "email is not valid"}


def test_upsert_form_invalid_gender_enum_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(gender="X")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert "gender must be one of" in json.loads(resp["body"])["error"]


def test_upsert_form_invalid_civil_status_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(civil_status="ENGAGED")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert "civil_status must be one of" in json.loads(resp["body"])["error"]


def test_upsert_form_invalid_birth_date_format_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(birth_date="05/01/1990")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "birth_date must be a valid date (YYYY-MM-DD)"}


def test_upsert_form_invalid_is_pep_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(is_pep="yes")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "is_pep must be true or false"}


def test_upsert_form_invalid_monthly_income_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(monthly_income=-100)

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "monthly_income must be >= 0"}


def test_upsert_form_invalid_nationality_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(nationality="NARNIA")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "nationality is not a valid country"}


def test_upsert_form_invalid_colombian_city_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=MagicMock(side_effect=AssertionError)))

    payload = _valid_payload(birth_country="COLOMBIA", birth_department="QUINDIO", birth_city="MOON_CITY")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "birth_department/birth_city is not valid"}


def test_upsert_form_foreign_birth_location_skips_catalog_check(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    saved = _fake_form_row()
    upsert_mock = MagicMock(return_value=saved)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=upsert_mock))

    payload = _valid_payload(birth_country="ESPANA", birth_department="Madrid", birth_city="Madrid")

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 200
    _, kwargs = upsert_mock.call_args
    assert kwargs["birth_department"] == "Madrid"
    assert kwargs["birth_city"] == "Madrid"


def test_upsert_form_bogota_locality_issuance_is_valid(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    saved = _fake_form_row()
    upsert_mock = MagicMock(return_value=saved)
    monkeypatch.setattr(h, "Forms", MagicMock(upsert=upsert_mock))

    payload = _valid_payload(
        document_issuance_country="COLOMBIA",
        document_issuance_department="CUNDINAMARCA",
        document_issuance_city="USAQUEN",
    )

    resp = h.handler(_authed_event(payload), None)

    assert resp["statusCode"] == 200
    _, kwargs = upsert_mock.call_args
    assert kwargs["document_issuance_city"] == "USAQUEN"


def test_upsert_form_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler({"headers": {}, "body": json.dumps(_valid_payload())}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}
