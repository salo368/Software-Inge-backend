"""Unit tests for the files/get_upload_url Lambda."""
from __future__ import annotations

import json
from uuid import uuid4
from unittest.mock import MagicMock


def _authed_event(body: dict) -> dict:
    return {
        "headers": {"Authorization": "Bearer tok"},
        "body": json.dumps(body),
    }


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(return_value=(user, MagicMock())),
    )
    return user


def test_get_upload_url_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    process_id = uuid4()
    proc = MagicMock(id=process_id, user_id=user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
    monkeypatch.setattr(h, "presign_upload", MagicMock(return_value="https://s3.test/upload"))

    resp = h.handler(
        _authed_event({
            "process_id": str(process_id),
            "file_type": "declaracion_renta",
            "content_type": "application/pdf",
            "original_name": "declaración renta 2025.pdf",
        }),
        None,
    )

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["upload_url"] == "https://s3.test/upload"
    assert body["content_type"] == "application/pdf"
    assert body["key"].startswith(f"processes/{process_id}/declaracion_renta/")
    assert body["key"].endswith(".pdf")
    # Metadata must be percent-encoded so the accented filename survives.
    assert "%20" in body["upload_headers"]["x-amz-meta-original-name"]


def test_get_upload_url_invalid_file_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(
        _authed_event({
            "process_id": str(uuid4()),
            "file_type": "not_a_real_type",
            "content_type": "application/pdf",
        }),
        None,
    )

    assert resp["statusCode"] == 400
    assert "file_type must be one of" in json.loads(resp["body"])["error"]


def test_get_upload_url_process_of_other_user_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch, user_id="me")

    other_user_process = MagicMock(id=uuid4(), user_id="someone-else")
    monkeypatch.setattr(
        h, "Processes", MagicMock(get_by_id=MagicMock(return_value=other_user_process))
    )
    monkeypatch.setattr(h, "presign_upload", MagicMock(side_effect=AssertionError))

    resp = h.handler(
        _authed_event({
            "process_id": str(uuid4()),
            "file_type": "declaracion_renta",
            "content_type": "application/pdf",
        }),
        None,
    )

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "process_not_found"}
