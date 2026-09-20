"""Unit tests for the banks/list_banks Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def test_list_banks_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    b1 = MagicMock(public_dict=MagicMock(return_value={"id": 1, "name": "Bancolombia"}))
    b2 = MagicMock(public_dict=MagicMock(return_value={"id": 2, "name": "Davivienda"}))
    monkeypatch.setattr(h, "Banks", MagicMock(list_active=MagicMock(return_value=[b1, b2])))

    resp = h.handler({}, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == {"banks": [{"id": 1, "name": "Bancolombia"}, {"id": 2, "name": "Davivienda"}]}
    for b in (b1, b2):
        # each Bank.public_dict must receive the assets base URL
        b.public_dict.assert_called_once_with(h.ASSETS_BASE_URL)


def test_list_banks_empty(load_handler, monkeypatch):
    """No active banks in the catalog: caller gets an empty list, still 200."""
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Banks", MagicMock(list_active=MagicMock(return_value=[])))

    resp = h.handler({}, None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"banks": []}


def test_list_banks_orm_failure_returns_500(load_handler, monkeypatch):
    """Unhandled exception in the ORM must be swallowed as internal_server_error,
    not leak the stack trace."""
    h = load_handler(__file__)
    monkeypatch.setattr(
        h, "Banks", MagicMock(list_active=MagicMock(side_effect=RuntimeError("db is down")))
    )

    resp = h.handler({}, None)

    assert resp["statusCode"] == 500
    assert json.loads(resp["body"]) == {"error": "internal_server_error"}
