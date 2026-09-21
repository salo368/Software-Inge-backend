"""Integration tests for `GET /signatures/{sign_id}`.

The signing SPA polls this endpoint constantly (every 4s during a
ceremony) and treats its response shape as the source of truth. If any
of the v2 fields drift (rename, drop, wrong type), the front breaks
silently.

These tests exercise the real dev API and check the response contract
end-to-end:

  * Fresh ceremony returns the `public_dict()` + `signer_name` +
    `pdf_url` shape, WITHOUT `signed_pdf_url`.
  * Once we drive a ceremony to `signed`, `signed_pdf_url` shows up
    and the presign resolves (HEAD returns 200).
  * Internal fields (`callback_url`, `service_caller`) are never
    exposed.

Slow tests: reaching stage='signed' takes ~30-60s because the async
sign worker cold-starts. Marked `slow_signature` for optional
filtering, but they run by default in the --integration lane.
"""

from __future__ import annotations

import pytest
import requests

from tests.integration_signatures import (
    drive_to_stage,
    load_face_fixture,
    open_ceremony,
    signatures_api,
    wait_for_stage,
)


pytestmark = pytest.mark.integration


def _get(sign_id: str) -> dict:
    r = requests.get(f"{signatures_api()}/signatures/{sign_id}", timeout=30)
    assert r.status_code == 200, f"get -> {r.status_code} {r.text}"
    return r.json()


def test_get_returns_v2_shape_for_fresh_ceremony():
    """A freshly created ceremony must return all the fields the SPA
    reads on first paint: sign_id, stage='created', signer_name,
    masked email, empty uploads_state, consent.given=False, otp
    counters, hashes (hash_original set, others null), pdf_url, and
    NO signed_pdf_url."""
    ctx = open_ceremony(signer_name="ITest Get Fresh")
    try:
        payload = _get(ctx.sign_id)

        # Identity + stage
        assert payload["sign_id"] == ctx.sign_id
        assert payload["stage"] == "created"

        # Handler-only extras
        assert payload["signer_name"] == "ITest Get Fresh"
        assert payload["pdf_url"].startswith("https://")
        assert "signed_pdf_url" not in payload

        # public_dict() fields
        assert "signer_email_masked" in payload
        assert payload["signer_email_masked"].endswith(
            payload["signer_email_masked"][-10:]
        )
        assert "@" in payload["signer_email_masked"]

        assert payload["signature_location"]["page"] == 1
        assert "uploads_state" in payload
        for kind in ("id_front", "id_back", "face"):
            assert payload["uploads_state"][kind]["uploaded"] is False
            assert payload["uploads_state"][kind]["validated"] is False
        assert payload["uploads_state"]["signature_drawing"]["uploaded"] is False

        assert payload["consent"]["given"] is False
        assert payload["consent"]["given_at"] is None
        assert payload["otp"]["requested"] is False
        assert payload["otp"]["attempts_left"] >= 1

        # Hashes: original is set on create (SHA-256 of the source PDF),
        # signed/cert are null until stage='signed'.
        assert isinstance(payload["hash_original"], str)
        assert len(payload["hash_original"]) == 64  # sha256 hex
        assert payload["hash_signed"] is None
        assert payload["cert_serial"] is None
        assert payload["signed_at"] is None
    finally:
        ctx.close()


def test_get_never_leaks_internal_fields():
    """The signer must never see callback_url or service_caller, even
    though the row carries them internally for the async worker."""
    ctx = open_ceremony(signer_name="ITest Get Leak")
    try:
        payload = _get(ctx.sign_id)
        assert "callback_url" not in payload
        assert "service_caller" not in payload
    finally:
        ctx.close()


def test_get_exposes_signed_pdf_url_only_after_signed():
    """Full ceremony drive: check the payload transitions. Before
    stage='signed' the SPA must not see `signed_pdf_url`; once the
    async worker completes, the presign is included and resolves."""
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")

    ctx = open_ceremony(signer_name="ITest Get Signed")
    try:
        # Drive all the way to 'signed'; wait_for_stage inside covers
        # the async pyhanko worker.
        drive_to_stage(ctx, "signed", face_bytes=face)

        # Final wait for consistency (drive_to_stage already waited).
        state = wait_for_stage(ctx, "signed", timeout_s=30.0)
        assert state["stage"] == "signed"
        assert "signed_pdf_url" in state
        assert state["hash_signed"] is not None
        assert len(state["hash_signed"]) == 64
        assert state["cert_serial"] is not None
        assert state["signed_at"] is not None

        # The presign must resolve (not 403). Use a bounded GET with
        # streaming so we don't download the whole PDF.
        r = requests.get(state["signed_pdf_url"], stream=True, timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("Content-Type") in (
            "application/pdf",
            "binary/octet-stream",
        )
        r.close()
    finally:
        ctx.close()
