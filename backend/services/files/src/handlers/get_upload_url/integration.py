"""Deploy-verification test for files/get_upload_url + files/on_upload worker.

This is the flagship "fuente de reposo" test: it exercises the full async
S3 -> worker -> DB flow end to end and asserts each of those side effects
actually persisted.

Strictly BLOCK-LOCAL: it never calls auth's or banks' HTTP endpoints. It
seeds its own user + bearer_token straight in Postgres via the helper,
and reads a bank id straight from the banks table (a static catalog, not
an API call). That way the files package can run in a pipeline where
auth/banks were NOT re-deployed in the same run.

  1. Seed a throwaway user + bearer token directly in Postgres.
  2. Read an active bank_id directly from the DB.
  3. Insert a throwaway process directly in Postgres (the created_at /
     status columns default from the schema).
  4. POST /files/upload-url as that user to get a presigned PUT.
  5. Actually PUT bytes to the returned URL.
  6. Poll Postgres until the on_upload S3 worker registers the file.
  7. Verify: S3 head matches; `files` row matches; the presigned
     download URL round-trips the same bytes.
  8. Tear down every artefact created.

Gated by --integration. See docs/repo-structure.md §13.3.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import requests

from tests.integration_helpers import (
    STAGE,
    api_base,
    bearer,
    cleanup_process,
    cleanup_s3_prefix,
    cleanup_user,
    create_test_user_directly,
    db_conn,
    query_one,
    query_scalar,
    s3_head,
    unique_name,
    wait_for,
)

pytestmark = pytest.mark.integration

FILES_BUCKET = os.environ.get("FILES_BUCKET", f"cdts-{STAGE}-files")


def _pick_active_bank_id() -> int:
    """Reads a bank id from the DB (banks is a static catalog, not an
    API contract). Bypassing /banks keeps this test block-local."""
    bid = query_scalar(
        "SELECT id FROM banks WHERE is_active = true ORDER BY id LIMIT 1"
    )
    assert bid is not None, (
        "no active banks in dev; seed the catalog before running this test"
    )
    return int(bid)


def _insert_process_directly(*, user_id: str, bank_id: int) -> str:
    """Inserts a throwaway process row and returns its id. Bypasses
    /processes so the files package doesn't depend on the processes
    block being freshly deployed."""
    pid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with db_conn() as c:
        # Column is `stage` (not `status`) and constrained to the enum
        # ('form','documents','signature','payment','done'). The upload flow
        # is entered from the 'documents' stage.
        c.run(
            "INSERT INTO processes "
            "(id, user_id, bank_id, amount, term_days, rate, stage, created_at) "
            "VALUES (:id, :uid, :bid, :amt, :term, :rate, :st, :now)",
            id=pid, uid=uuid.UUID(user_id), bid=bank_id,
            amt=Decimal("1000000"), term=180, rate=Decimal("12.5"),
            st="documents", now=now,
        )
    return str(pid)


def test_upload_flow_registers_file_row_and_s3_object():
    session = create_test_user_directly()
    email = session["email"]
    hdrs = bearer(session["token"])

    process_id: str | None = None
    s3_key: str | None = None

    try:
        # --- Step 1 & 2: seed a process straight in the DB so we have
        # something to attach a file to. Bank comes from the static catalog.
        bank_id = _pick_active_bank_id()
        process_id = _insert_process_directly(
            user_id=session["user_id"], bank_id=bank_id,
        )

        # --- Step 3: ask files/upload-url for a presigned PUT.
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

        # --- Step 4: actually PUT bytes to S3 using the presigned URL.
        # The bytes only need to be identifiable (a valid tiny PDF header).
        payload_bytes = b"%PDF-1.4\n% integration test\n%%EOF\n"
        put_resp = requests.put(
            upload_url, data=payload_bytes, headers=upload_headers, timeout=30
        )
        assert put_resp.status_code in (200, 204), put_resp.text

        # --- Step 5: state at rest #1: the object must be in S3.
        head = s3_head(FILES_BUCKET, s3_key)
        assert head is not None, f"S3 object {s3_key} not found after PUT"
        assert head["ContentLength"] == len(payload_bytes)
        assert head["ContentType"] == "application/pdf"

        # --- Step 6: state at rest #2: the on_upload worker must have
        # registered the file in the `files` table. S3 -> Lambda is async;
        # give it up to 30s with gentle polling.
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

        # --- Step 7: bonus check: /files/{id}/download-url returns a
        # usable presigned GET for the same object.
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
        # Reverse-order cleanup. Helpers swallow errors so a partially
        # created test still cleans up as much as it can.
        if s3_key:
            cleanup_s3_prefix(FILES_BUCKET, f"processes/{process_id}/")
        if process_id:
            cleanup_process(process_id)
        cleanup_user(email)
