"""Unit tests for the files/get_process_files Lambda (backoffice, admin only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID

_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def _patch_admin_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


def _event(query=None):
    return {"headers": {"Authorization": "Bearer adm"}, "queryStringParameters": query}


def _file(file_type, key):
    return MagicMock(
        id=UUID(int=1),
        file_type=file_type,
        original_name="cert.pdf",
        content_type="application/pdf",
        size_bytes=2048,
        uploaded_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
        s3_key=key,
    )


def test_get_process_files_lists_with_download_urls(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    files = MagicMock(list_by_process=MagicMock(return_value=[_file("BANK_CERT", "processes/p/bank.pdf")]))
    monkeypatch.setattr(h, "Files", files)
    presign = MagicMock(return_value="https://s3/signed")
    monkeypatch.setattr(h, "presign_download", presign)

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["files"]) == 1
    assert body["files"][0]["file_type"] == "BANK_CERT"
    assert body["files"][0]["url"] == "https://s3/signed"
    assert body["files"][0]["size_bytes"] == 2048
    files.list_by_process.assert_called_once_with(UUID(_PID))
    presign.assert_called_once_with(h.BUCKET, "processes/p/bank.pdf")


def test_get_process_files_empty(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    monkeypatch.setattr(h, "Files", MagicMock(list_by_process=MagicMock(return_value=[])))

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"files": []}


def test_get_process_files_invalid_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    files = MagicMock()
    monkeypatch.setattr(h, "Files", files)

    for query in (None, {"process_id": "nope"}):
        resp = h.handler(_event(query), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid process id"}
    files.list_by_process.assert_not_called()


def test_get_process_files_requires_admin_token(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    files = MagicMock()
    monkeypatch.setattr(h, "Files", files)

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 401
    files.list_by_process.assert_not_called()
