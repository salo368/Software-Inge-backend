"""Deploy-verification test for files/get_upload_url + files/on_upload worker.

This is the flagship "fuente de reposo" test: it exercises the full async
flow end-to-end.

  1. Sign up + login (throwaway user).
  2. Create a process (needs a real bank).
  3. Ask files/get-upload-url for a presigned PUT.
  4. Actually PUT bytes to S3.
  5. Poll until the on_upload S3 worker registers the file in Postgres.
  6. Verify: S3 head shows the object; files row matches its metadata; the
     size in DB matches the bytes we uploaded.
  7. Tear down every artefact we created.

Gated by --integration. See docs/repo-structure.md §13.3.
"""
from __future__ import annotations

import os

import pytest
import requests

from tests.integration_helpers import (
    STAGE,
    api_base,
    bearer,
    cleanup_process,
    cleanup_s3_prefix,
    cleanup_user,
    query_one,
    s3_head,
    signup_and_login,
    unique_name,
    wait_for,
)

pytestmark = pytest.mark.integration

FILES_BUCKET = os.environ.get("FILES_BUCKET", f"cdts-{STAGE}-files")


def _first_bank_id(auth_bearer: dict) -> int:
    """Picks any active bank so the process can be created. The banks
    service is authenticated only on some paths; /banks is public."""
    resp = requests.get(f"{api_base('banks')}/banks", timeout=15)
    resp.raise_for_status()
    banks = resp.json()["banks"]
    assert banks, "no active banks in dev; seed the catalog before running this test"
    return banks[0]["id"]


def test_upload_flow_registers_file_row_and_s3_object():
    session = signup_and_login()
    email = session["email"]
    hdrs = bearer(session["token"])

    process_id: str | None = None
    s3_key: str | None = None

    try:
        # --- Step 1: create a process so the file has somewhere to attach.
        bank_id = _first_bank_id(hdrs)
        proc_resp = requests.post(
            f"{api_base('processes')}/processes",
            headers=hdrs,
            json={
                "bank_id": bank_id,
                "amount": "1000000",
                "term_days": 180,
                "rate": "12.5",
            },
            timeout=15,
        )
        assert proc_resp.status_code == 201, proc_resp.text
        process_id = proc_resp.json()["process"]["id"]

        # --- Step 2: ask for a presigned upload URL.
        original_name = unique_name("doc") + ".pdf"
        url_resp = requests.post(
            f"{api_base('files')}/files/upload-url",
            headers=hdrs,
            json={
                "process_id": process_id,
                "file_type": "declaracion_renta",
                "content_type": "application/pdf",
                "original_name": original_name,
            },
            timeout=15,
        )
        assert url_resp.status_code == 200, url_resp.text
        url_body = url_resp.json()
        upload_url = url_body["upload_url"]
        s3_key = url_body["key"]
        upload_headers = url_body["upload_headers"]

        # --- Step 3: actually PUT bytes to S3 using the presigned URL.
        # The bytes only need to be identifiable (a valid tiny PDF header).
        payload_bytes = b"%PDF-1.4\n% integration test\n%%EOF\n"
        put_resp = requests.put(
            upload_url, data=payload_bytes, headers=upload_headers, timeout=30
        )
        assert put_resp.status_code in (200, 204), put_resp.text

        # --- Step 4: fuente de reposo #1: el objeto debe estar en S3.
        head = s3_head(FILES_BUCKET, s3_key)
        assert head is not None, f"S3 object {s3_key} not found after PUT"
        assert head["ContentLength"] == len(payload_bytes)
        assert head["ContentType"] == "application/pdf"

        # --- Step 5: fuente de reposo #2: el worker on_upload debe haber
        # insertado la fila en `files`. S3 -> Lambda es async; damos hasta 30s
        # con polling suave.
        row = wait_for(
            lambda: query_one(
                "SELECT id, s3_key, file_type, size_bytes, content_type, original_name "
                "FROM files WHERE s3_key = :k",
                k=s3_key,
            ),
            timeout_s=30.0,
            interval_s=2.0,
        )
        assert row is not None, (
            f"on_upload worker did not register {s3_key} in files table within 30s"
        )
        assert row["file_type"] == "declaracion_renta"
        assert row["size_bytes"] == len(payload_bytes)
        assert row["content_type"] == "application/pdf"
        # original_name is stored percent-decoded by the worker.
        assert row["original_name"] == original_name

        # --- Step 6: bonus verification: /files/{id}/download-url returns
        # a usable presigned GET for the same object.
        dl = requests.get(
            f"{api_base('files')}/files/{row['id']}/download-url",
            headers=hdrs,
            timeout=15,
        )
        assert dl.status_code == 200, dl.text
        download_url = dl.json()["download_url"]
        got = requests.get(download_url, timeout=30)
        assert got.status_code == 200
        assert got.content == payload_bytes

    finally:
        # Cleanup in reverse order of creation. Best-effort: helpers swallow
        # errors so a partially-created test still cleans up as much as it can.
        if s3_key:
            cleanup_s3_prefix(FILES_BUCKET, f"processes/{process_id}/")
        if process_id:
            cleanup_process(process_id)
        cleanup_user(email)
