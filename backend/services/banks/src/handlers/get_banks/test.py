"""Unit tests for the banks/get_banks Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _fake_bank(**overrides):
    defaults = dict(
        id=1,
        code="bancolombia",
        name="Bancolombia",
        logo_key="banks/bancolombia.png",
        description="desc",
        tier="AAA",
        rating_by="Fitch Ratings",
        highlights=["a", "b"],
    )
    defaults.update(overrides)
    bank = MagicMock()
    bank.configure_mock(**defaults)
    return bank


# Happy path: active banks come back, each with their logo_url resolved
# against ASSETS_BASE_URL.
def test_get_banks_happy_path(load_handler, monkeypatch):

    h = load_handler(__file__)

    b1 = _fake_bank(id=1, code="bancolombia", name="Bancolombia")
    b2 = _fake_bank(id=2, code="davivienda", name="Davivienda")
    monkeypatch.setattr(h, "Banks", MagicMock(get_all=MagicMock(return_value=[b1, b2])))

    resp = h.handler({}, None)

    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert [b["id"] for b in body["banks"]] == [1, 2]
    assert [b["name"] for b in body["banks"]] == ["Bancolombia", "Davivienda"]

    expected_logo_url = (
        f"{h.ASSETS_BASE_URL.rstrip('/')}/banks/bancolombia.png"
        if h.ASSETS_BASE_URL
        else "banks/bancolombia.png"
    )
    assert body["banks"][0]["logo_url"] == expected_logo_url

    h.Banks.get_all.assert_called_once_with(active=True)


# No active banks in the catalog: caller gets an empty list, still 200.
def test_get_banks_empty(load_handler, monkeypatch):

    h = load_handler(__file__)

    monkeypatch.setattr(h, "Banks", MagicMock(get_all=MagicMock(return_value=[])))

    resp = h.handler({}, None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"banks": []}


# Unhandled exception in the ORM must be swallowed as internal_server_error,
# not leak the stack trace.
def test_get_banks_orm_failure_returns_500(load_handler, monkeypatch):

    h = load_handler(__file__)

    monkeypatch.setattr(
        h, "Banks", MagicMock(get_all=MagicMock(side_effect=RuntimeError("db is down")))
    )

    resp = h.handler({}, None)

    assert resp["statusCode"] == 500
    assert json.loads(resp["body"]) == {"error": "internal_server_error"}
