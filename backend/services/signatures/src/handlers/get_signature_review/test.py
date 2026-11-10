"""Unit tests for the signatures/get_signature_review Lambda (backoffice, admin only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID

_SID = "312e7c0b-ace6-44f0-bf09-7ae729a41f30"


def _patch_admin_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


def _event(query=None):
    return {"headers": {"Authorization": "Bearer adm"}, "queryStringParameters": query}


def _row(**overrides):
    values = dict(
        id=UUID(_SID),
        stage="SIGNED",
        signatory="Ana Gomez",
        email="ana@example.com",
        created_at=datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc),
        signed_at=datetime(2026, 11, 9, 2, 6, tzinfo=timezone.utc),
        otp_tries=1,
        doc_hash="a" * 64,
        signed_hash="b" * 64,
        signing_data={"ip": "1.2.3.4", "user_agent": "UA", "accept_language": "es", "resolved_at": "2026-11-09T02:05:00+00:00", "x": 1},
        doc_s3_key="doc.pdf",
        raw_signed_s3_key="raw.pdf",
        signed_s3_key="signed.pdf",
        draw_s3_key="draw.png",
        id_front_s3_key="front.jpg",
        id_back_s3_key="back.jpg",
        id_face_s3_key=None,
    )
    values.update(overrides)
    return MagicMock(**values)


def test_get_signature_review_returns_the_whole_record(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=_row())))
    monkeypatch.setattr(h, "presign_download", lambda bucket, key: f"https://s3/{key}")

    resp = h.handler(_event({"signature_id": _SID}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["stage"] == "SIGNED"
    assert body["email"] == "ana@example.com"
    assert body["otp_tries"] == 1
    assert body["signed_url"] == "https://s3/signed.pdf"
    assert body["draw_url"] == "https://s3/draw.png"
    assert body["evidences"] == {"ID_FRONT": "https://s3/front.jpg", "ID_BACK": "https://s3/back.jpg", "FACE": None}
    # Only the known telemetry keys travel.
    assert body["telemetry"] == {"ip": "1.2.3.4", "user_agent": "UA", "accept_language": "es", "resolved_at": "2026-11-09T02:05:00+00:00"}
    assert body["expires_at"].startswith("2026-11-09 02:15:00")


def test_get_signature_review_before_signing(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    row = _row(stage="BIOMETRICS", signed_at=None, signing_data=None, raw_signed_s3_key=None, signed_s3_key=None, draw_s3_key=None)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_download", lambda bucket, key: f"https://s3/{key}")

    body = json.loads(h.handler(_event({"signature_id": _SID}), None)["body"])

    assert body["signed_url"] is None
    assert body["draw_url"] is None
    assert body["telemetry"] == {"ip": None, "user_agent": None, "accept_language": None, "resolved_at": None}


def test_get_signature_review_not_found_and_invalid_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    assert h.handler(_event({"signature_id": _SID}), None)["statusCode"] == 404
    assert h.handler(_event({"signature_id": "nope"}), None)["statusCode"] == 400


def test_get_signature_review_requires_admin_token(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    signatures = MagicMock()
    monkeypatch.setattr(h, "Signatures", signatures)

    assert h.handler(_event({"signature_id": _SID}), None)["statusCode"] == 401
    signatures.get_by_id.assert_not_called()
