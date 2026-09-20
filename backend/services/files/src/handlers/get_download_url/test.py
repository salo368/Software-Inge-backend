"""Unit tests for the files/get_download_url Lambda."""
from __future__ import annotations

import json
from uuid import uuid4
from unittest.mock import MagicMock


def _authed_event(file_id: str) -> dict:
    return {
        "headers": {"Authorization": "Bearer tok"},
        "pathParameters": {"id": file_id},
    }


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(return_value=(user, MagicMock())),
    )
    return user


def test_get_download_url_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    file_id = uuid4()
    file_row = MagicMock(
        process_id=uuid4(),
        s3_key="processes/x/declaracion_renta/y.pdf",
        original_name="doc.pdf",
        content_type="application/pdf",
    )
    monkeypatch.setattr(h, "Files", MagicMock(get_by_id=MagicMock(return_value=file_row)))
    monkeypatch.setattr(
        h,
        "Processes",
        MagicMock(get_by_id=MagicMock(return_value=MagicMock(user_id=user.id))),
    )
    monkeypatch.setattr(h, "presign_download", MagicMock(return_value="https://s3.test/dl"))

    resp = h.handler(_authed_event(str(file_id)), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["download_url"] == "https://s3.test/dl"
    assert body["original_name"] == "doc.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["expires_in"] == 900


def test_get_download_url_invalid_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Files", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_authed_event("not-a-uuid"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid file id"}


def test_get_download_url_file_of_other_user_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch, user_id="me")

    file_row = MagicMock(process_id=uuid4(), s3_key="k", original_name="n", content_type="t")
    monkeypatch.setattr(h, "Files", MagicMock(get_by_id=MagicMock(return_value=file_row)))
    monkeypatch.setattr(
        h,
        "Processes",
        MagicMock(get_by_id=MagicMock(return_value=MagicMock(user_id="somebody-else"))),
    )
    monkeypatch.setattr(h, "presign_download", MagicMock(side_effect=AssertionError))

    resp = h.handler(_authed_event(str(uuid4())), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "file_not_found"}
