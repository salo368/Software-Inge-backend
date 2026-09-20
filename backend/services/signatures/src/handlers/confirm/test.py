"""Unit tests for the signatures/confirm Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def _event(token: str, body: dict) -> dict:
    return {"pathParameters": {"token": token}, "body": json.dumps(body)}


def _row_ready(**overrides) -> MagicMock:
    """A signature row ready to be confirmed: OTP requested, all evidence
    uploaded, not yet signed."""
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    row = MagicMock(
        stage="otp",
        otp_hash="hashed-otp",
        otp_expires_at=future,
        otp_attempts=0,
        pdf_key="signatures/xyz/investment-order.pdf",
        cedula_front_key="signatures/xyz/cedula_front.jpg",
        cedula_back_key="signatures/xyz/cedula_back.jpg",
        face_key="signatures/xyz/face.jpg",
        signature_key="signatures/xyz/signature.png",
        process_id="p-1",
        email="u@x.co",
        page=1,
        pos_x=10,
        pos_y=20,
        otp_matches=MagicMock(return_value=True),
        mark_signed=MagicMock(),
        register_failed_attempt=MagicMock(return_value=2),
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


def test_confirm_happy_path_seals_ceremony(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row_ready()
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))

    proc = MagicMock(stage="signature", form_snapshot=None, advance_to=MagicMock())
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))

    monkeypatch.setattr(h, "download_bytes", MagicMock(return_value=b"fake-bytes"))
    monkeypatch.setattr(h, "stamp_signature", MagicMock(return_value=b"stamped-pdf"))
    monkeypatch.setattr(h, "build_certificate", MagicMock(return_value=b"cert-pdf"))
    monkeypatch.setattr(h, "append_pdf", MagicMock(return_value=b"final-pdf"))
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock())
    monkeypatch.setattr(h, "presign_download", MagicMock(return_value="https://s3.test/signed"))
    monkeypatch.setattr(
        h, "Files", MagicMock(get_by_key=MagicMock(return_value=None), register_from_s3=MagicMock())
    )

    resp = h.handler(_event("xyz", {"otp": "123456"}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "signed"
    assert body["signed_pdf_url"] == "https://s3.test/signed"
    row.mark_signed.assert_called_once()
    proc.advance_to.assert_called_once_with("payment")
    h.Files.register_from_s3.assert_called_once()


def test_confirm_invalid_otp_returns_401_with_remaining(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row_ready()
    row.otp_matches.return_value = False
    row.register_failed_attempt.return_value = 1
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    monkeypatch.setattr(h.db_session, "commit", MagicMock())
    # None of the downstream steps must run on a bad OTP.
    monkeypatch.setattr(h, "download_bytes", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event("xyz", {"otp": "wrong"}), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_otp:1"}
    row.register_failed_attempt.assert_called_once()
    # The failed attempt MUST be persisted before raising, otherwise the
    # decorator's rollback would give the caller free guesses.
    h.db_session.commit.assert_called_once()


def test_confirm_missing_evidence_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row_ready(signature_key=None)  # signature evidence missing
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "download_bytes", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event("xyz", {"otp": "123456"}), None)

    assert resp["statusCode"] == 409
    err = json.loads(resp["body"])["error"]
    assert err.startswith("missing_evidence:")
    assert "signature" in err
    row.mark_signed.assert_not_called()
