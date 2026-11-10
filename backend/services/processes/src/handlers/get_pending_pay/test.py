"""Unit tests for the processes/get_pending_pay Lambda."""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

from libs.utils.lambda_invoke import LambdaInvokeError

_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def _event(process_id: str = _PID, headers: dict | None = None) -> dict:
    return {
        "headers": headers if headers is not None else {"Authorization": "Bearer tok"},
        "queryStringParameters": {"process_id": process_id},
    }


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.UserBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user)))
    return user


def _process(user_id, stage="PAYMENT", amount="3000000.00"):
    return MagicMock(id=UUID(_PID), user_id=user_id, stage=stage, amount=Decimal(amount))


def _payments_response(*amounts):
    payments = [{"id": f"p{i}", "amount": a, "s3_file": f"payments/{_PID}/{i}.png"} for i, a in enumerate(amounts)]
    return {"statusCode": 200, "body": json.dumps({"payments": payments})}


def _patch(h, monkeypatch, process, invoke):
    processes = MagicMock(get_by_id_for_update=MagicMock(return_value=process), advance_to_review=MagicMock())
    monkeypatch.setattr(h, "Processes", processes)
    monkeypatch.setattr(h, "invoke_sync", invoke)
    return processes


def test_partial_payment_reports_pending_and_keeps_stage(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)
    invoke = MagicMock(return_value=_payments_response("1000000.00", "500000.00"))
    processes = _patch(h, monkeypatch, _process(user.id), invoke)

    resp = h.handler(_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "process_id": _PID, "amount": 3000000.0,
        "paid": 1500000.0, "pending": 1500000.0, "stage": "PAYMENT",
    }
    processes.advance_to_review.assert_not_called()
    assert invoke.call_args.kwargs == {
        "function_key": "list_process_payments",
        "payload": {"body": json.dumps({"process_id": _PID})},
        "service": "payments",
    }


def test_no_payments_yet(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)
    processes = _patch(h, monkeypatch, _process(user.id), MagicMock(return_value=_payments_response()))

    resp = h.handler(_event(), None)

    body = json.loads(resp["body"])
    assert body["paid"] == 0.0 and body["pending"] == 3000000.0 and body["stage"] == "PAYMENT"
    processes.advance_to_review.assert_not_called()


def test_exact_payment_advances_to_review(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)
    invoke = MagicMock(return_value=_payments_response("2999999.99", "0.01"))
    processes = _patch(h, monkeypatch, _process(user.id), invoke)

    resp = h.handler(_event(), None)

    assert json.loads(resp["body"]) == {
        "process_id": _PID, "amount": 3000000.0,
        "paid": 3000000.0, "pending": 0.0, "stage": "REVIEW",
    }
    processes.advance_to_review.assert_called_once_with(UUID(_PID))


def test_overpayment_advances_to_review_without_changing_the_amount(load_handler, monkeypatch):
    """The amount is fixed by the signed investment order: paying more
    closes the payment stage but never rewrites the process."""
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)
    invoke = MagicMock(return_value=_payments_response("3000000.00", "500000.00"))
    processes = _patch(h, monkeypatch, _process(user.id), invoke)

    resp = h.handler(_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "process_id": _PID, "amount": 3000000.0,
        "paid": 3500000.0, "pending": 0.0, "stage": "REVIEW",
    }
    processes.advance_to_review.assert_called_once_with(UUID(_PID))
    assert invoke.call_count == 1


def test_payments_unreachable_returns_502(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)
    processes = _patch(
        h, monkeypatch, _process(user.id),
        MagicMock(side_effect=LambdaInvokeError("fn", "boto_error", "timeout")),
    )

    resp = h.handler(_event(), None)

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]) == {"error": "payments_unavailable"}
    processes.advance_to_review.assert_not_called()


def test_process_not_in_payment_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)
    _patch(h, monkeypatch, _process(user.id, stage="SIGNATURE"), MagicMock(side_effect=AssertionError))

    resp = h.handler(_event(), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "process_not_in_payment_stage"}


def test_other_users_process_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    _patch(h, monkeypatch, _process("someone-else"), MagicMock(side_effect=AssertionError))

    resp = h.handler(_event(), None)

    assert resp["statusCode"] == 404


def test_invalid_process_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    resp = h.handler(_event("nope"), None)

    assert resp["statusCode"] == 400


def test_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler(_event(headers={}), None)

    assert resp["statusCode"] == 401
