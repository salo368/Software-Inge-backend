"""Unit tests for the banks/simulate Lambda."""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock


def _event(body: dict | None) -> dict:
    return {"body": json.dumps(body) if body is not None else None}


def _fake_bank(**overrides):
    defaults = dict(
        id=1,
        code="bank",
        name="Bank",
        logo_key="banks/bank.png",
        description="desc",
        tier="AAA",
        rating_by="Fitch Ratings",
        highlights=[],
    )
    defaults.update(overrides)
    bank = MagicMock()
    bank.configure_mock(**defaults)
    return bank


# Happy path: get_ranked_rates returns the (bank_id, rate) pairs already
# ranked, and the handler just maps those bank_ids to full bank data --
# bank 3 has no active-bank match and must be dropped silently.
def test_simulate_happy_path_sorts_by_rate_desc(load_handler, monkeypatch):

    h = load_handler(__file__)

    b1 = _fake_bank(id=1, name="Bank A")
    b2 = _fake_bank(id=2, name="Bank B")
    monkeypatch.setattr(h, "Banks", MagicMock(get_all=MagicMock(return_value=[b1, b2])))

    # Already ranked best-to-worst; bank 3 has no entry in Banks.get_all.
    monkeypatch.setattr(
        h,
        "get_ranked_rates",
        MagicMock(return_value=[(2, Decimal("12.5")), (3, Decimal("11.0")), (1, Decimal("10.0"))]),
    )

    resp = h.handler(_event({"amount": "1000000", "term_days": 120}), None)

    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["amount"] == 1000000
    assert body["term_days"] == 120
    # Order preserved as returned by get_ranked_rates; bank 3 dropped.
    assert [b["id"] for b in body["banks"]] == [2, 1]
    for b in body["banks"]:
        assert b["interest"] > 0
        assert b["final"] > b["interest"]

    h.get_ranked_rates.assert_called_once_with(Decimal("1000000"), 120)


# Invalid amount -> 400 before ever touching get_ranked_rates.
def test_simulate_invalid_amount_returns_400(load_handler, monkeypatch):

    h = load_handler(__file__)

    monkeypatch.setattr(h, "get_ranked_rates", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event({"amount": "-5", "term_days": 180}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_amount"}


# term_days <= 0 -> 400. Any positive term is otherwise accepted now (bands
# replaced the old fixed-set validation); it's the band lookup, not input
# parsing, that decides whether a term is actually covered.
def test_simulate_invalid_term_returns_400(load_handler):

    h = load_handler(__file__)

    resp = h.handler(_event({"amount": "1000000", "term_days": 0}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_term_days"}
