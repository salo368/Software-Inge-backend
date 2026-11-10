"""Unit tests for the banks/get_bank Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _fake_bank(**overrides):
    defaults = dict(
        id=1,
        code="bancolombia",
        name="Bancolombia",
        logo_key="banks/bancolombia.png",
        io_key="order-forms/bancolombia.pdf",
        description="desc",
        tier="AAA",
        rating_by="Fitch Ratings",
        highlights=["a", "b"],
        is_active=True,
    )
    defaults.update(overrides)
    bank = MagicMock()
    bank.configure_mock(**defaults)
    return bank


def test_get_bank_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    bank = _fake_bank()
    monkeypatch.setattr(h, "Banks", MagicMock(get_by_id=MagicMock(return_value=bank)))

    resp = h.handler({"queryStringParameters": {"bank_id": "1"}}, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["id"] == 1
    assert body["code"] == "bancolombia"
    expected_io_url = (
        f"{h.ASSETS_BASE_URL.rstrip('/')}/order-forms/bancolombia.pdf"
        if h.ASSETS_BASE_URL
        else "order-forms/bancolombia.pdf"
    )
    assert body["io_url"] == expected_io_url
    assert body["is_active"] is True
    h.Banks.get_by_id.assert_called_once_with(1)


def test_get_bank_missing_io_key_returns_none_url(load_handler, monkeypatch):
    h = load_handler(__file__)

    bank = _fake_bank(io_key=None)
    monkeypatch.setattr(h, "Banks", MagicMock(get_by_id=MagicMock(return_value=bank)))

    resp = h.handler({"queryStringParameters": {"bank_id": "1"}}, None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["io_url"] is None


def test_get_bank_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "Banks", MagicMock(get_by_id=MagicMock(return_value=None)))

    resp = h.handler({"queryStringParameters": {"bank_id": "999"}}, None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "bank_not_found"}


def test_get_bank_missing_bank_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Banks", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"queryStringParameters": {}}, None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid bank_id"}


def test_get_bank_non_numeric_bank_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Banks", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"queryStringParameters": {"bank_id": "abc"}}, None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid bank_id"}
