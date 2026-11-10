"""Unit tests for the files/list_process_files internal Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4


def _fake_file(**overrides):
    defaults = dict(
        id=uuid4(),
        file_type="BANK_CERT",
        original_name="cert.pdf",
        uploaded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_list_process_files_returns_registered_files(load_handler, monkeypatch):
    h = load_handler(__file__)

    process_id = str(uuid4())
    rows = [_fake_file(file_type="BANK_CERT"), _fake_file(file_type="TAX_DECLARATION")]
    monkeypatch.setattr(h, "Files", MagicMock(list_by_process=MagicMock(return_value=rows)))

    resp = h.handler({"body": json.dumps({"process_id": process_id})}, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert [f["file_type"] for f in body["files"]] == ["BANK_CERT", "TAX_DECLARATION"]
    h.Files.list_by_process.assert_called_once_with(process_id)


def test_list_process_files_empty(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "Files", MagicMock(list_by_process=MagicMock(return_value=[])))

    resp = h.handler({"body": json.dumps({"process_id": str(uuid4())})}, None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"files": []}


def test_list_process_files_missing_process_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "Files", MagicMock(list_by_process=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"body": "{}"}, None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "process_id is required"}
