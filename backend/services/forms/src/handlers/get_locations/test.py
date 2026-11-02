"""Unit tests for the forms/get_locations Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _event(query: dict | None) -> dict:
    return {"queryStringParameters": query}


def test_get_locations_colombian_locations(load_handler, monkeypatch):
    h = load_handler(__file__)

    fake_data = {"QUINDIO": {"label": "Quindío", "cities": {"ARMENIA": {"label": "Armenia"}}}}
    monkeypatch.setattr(h, "handle_colombian_locations", MagicMock(return_value=fake_data))
    monkeypatch.setattr(h, "handle_countries", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event({"type": "colombian_locations"}), None)

    assert resp["statusCode"] == 200
    assert resp["headers"]["Cache-Control"] == "public, max-age=7200"
    assert json.loads(resp["body"]) == {"data": fake_data}


def test_get_locations_countries(load_handler, monkeypatch):
    h = load_handler(__file__)

    fake_data = {"COLOMBIA": {"label": "Colombia", "abbr": "CO"}}
    monkeypatch.setattr(h, "handle_countries", MagicMock(return_value=fake_data))
    monkeypatch.setattr(h, "handle_colombian_locations", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event({"type": "countries"}), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"data": fake_data}


def test_get_locations_missing_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "handle_colombian_locations", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "handle_countries", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event(None), None)

    assert resp["statusCode"] == 400
    assert "Invalid or missing 'type'" in json.loads(resp["body"])["error"]


def test_get_locations_invalid_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "handle_colombian_locations", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "handle_countries", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event({"type": "banks"}), None)

    assert resp["statusCode"] == 400
    assert "Invalid or missing 'type'" in json.loads(resp["body"])["error"]


def test_handle_colombian_locations_strips_dane_code_and_nests_localities(load_handler):
    h = load_handler(__file__)

    data = h.handle_colombian_locations()

    quindio = data["QUINDIO"]
    assert quindio["label"] == "Quindío"
    armenia = quindio["cities"]["ARMENIA"]
    assert armenia == {"label": "Armenia"}
    assert "dane_code" not in armenia

    bogota = data["CUNDINAMARCA"]["cities"]["BOGOTA_DC"]
    assert "dane_code" not in bogota
    assert bogota["localities"]["USAQUEN"] == {"label": "Usaquén"}
