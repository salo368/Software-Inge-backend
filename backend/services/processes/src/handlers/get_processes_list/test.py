"""Unit tests for the processes/get_processes_list Lambda (backoffice, admin only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _patch_admin_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


def _event(body=None, query=None):
    event = {"headers": {"Authorization": "Bearer adm"}}
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = query
    return event


def _process(n, form=None, stage="PAYMENT"):
    return MagicMock(
        id=f"p-{n}", user_id=f"u-{n}", bank_id=1, amount=Decimal("1000000.00"), term=180,
        rate=Decimal("12.50"), stage=stage, signature_id=None, submitted_form=form,
        created_at=_NOW, updated_at=_NOW,
    )


def _patch_processes(h, monkeypatch, rows, total):
    processes = MagicMock(search=MagicMock(return_value=rows), count_search=MagicMock(return_value=total))
    monkeypatch.setattr(h, "Processes", processes)
    return processes


def test_get_processes_list_shape_and_applicant(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    form = {
        "name": "Ana", "second_name": None, "last_name": "Gomez", "second_last_name": "Ruiz",
        "email": "ana@x.co", "document_type": "CC", "document_number": "123",
    }
    processes = _patch_processes(h, monkeypatch, [_process(1, form), _process(2, None, stage="FORM")], total=31)

    resp = h.handler(_event({"page": 2, "page_size": 2}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["count"] == 2
    assert body["pagination"] == {"offset": 2, "limit": 2, "total": 31}
    assert body["results"][0] == {
        "id": "p-1", "user_id": "u-1", "bank_id": 1, "amount": 1000000.0, "term": 180, "rate": 12.5,
        "stage": "PAYMENT", "signature_id": None,
        "applicant": {"full_name": "Ana Gomez Ruiz", "email": "ana@x.co", "document_type": "CC", "document_number": "123"},
        "created_at": "2026-01-01 00:00:00+00:00", "updated_at": "2026-01-01 00:00:00+00:00",
    }
    # Form not filled yet (FORM stage): the applicant is all nulls, not an error.
    assert body["results"][1]["applicant"] == {
        "full_name": None, "email": None, "document_type": None, "document_number": None,
    }
    processes.search.assert_called_once_with(None, [], "", 2, 2)
    processes.count_search.assert_called_once_with(None, [], "")


def test_get_processes_list_passes_filters(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    processes = _patch_processes(h, monkeypatch, [], total=0)

    h.handler(_event({"search": "  ana  ", "bank_id": 3, "stages": ["payment", "REVIEW", "payment"]}), None)

    processes.search.assert_called_once_with(3, ["PAYMENT", "REVIEW"], "ana", 20, 0)
    processes.count_search.assert_called_once_with(3, ["PAYMENT", "REVIEW"], "ana")


def test_get_processes_list_accepts_query_string(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    processes = _patch_processes(h, monkeypatch, [], total=0)

    h.handler(_event(query={"bank_id": "2", "stages": "DOCUMENTS, SIGNATURE", "page_size": "5"}), None)

    processes.search.assert_called_once_with(2, ["DOCUMENTS", "SIGNATURE"], "", 5, 0)


def test_get_processes_list_rejects_bad_params(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    processes = _patch_processes(h, monkeypatch, [], total=0)

    for body, error in (
        ({"bank_id": "x"}, "invalid_bank_id"),
        ({"bank_id": 0}, "invalid_bank_id"),
        ({"stages": ["NOPE"]}, "invalid_stages"),
        ({"stages": "FORM,NOPE"}, "invalid_stages"),
        ({"stages": 5}, "invalid_stages"),
        ({"search": 5}, "invalid_search"),
        ({"page": 0}, "invalid_page"),
        ({"page_size": 101}, "invalid_page_size"),
    ):
        resp = h.handler(_event(body), None)

        assert resp["statusCode"] == 400, body
        assert json.loads(resp["body"]) == {"error": error}, body
    processes.search.assert_not_called()


def test_get_processes_list_user_token_is_rejected(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    processes = _patch_processes(h, monkeypatch, [], total=0)

    resp = h.handler(_event(), None)

    assert resp["statusCode"] == 401
    processes.search.assert_not_called()


def test_get_processes_list_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
