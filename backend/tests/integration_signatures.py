"""End-to-end helpers for `signatures/**/integration.py`.

This module exists so every colocated integration test can drive a
signature ceremony against real dev infra WITHOUT copy-pasting 300
lines of "upload evidence, validate, consent, request OTP with debug
key, verify OTP, wait for sign worker" bookkeeping.

Design decisions:

    * `open_ceremony()` uploads a synthetic PDF to the signatures
      bucket at `_test-sources/<uuid>.pdf`, presigns a GET, and posts
      to `POST /signatures` with the M2M service key. The test-only
      source path is covered by the bucket's 30-day lifecycle rule so
      forgotten fixtures self-clean.
    * `drive_to_stage()` runs the ceremony up to a target stage.
      Callers pick the earliest stage they need (`identity` if they
      only test upload/validate, `consent` if they test the consent
      step, and so on) so each integration test does the minimum work
      for the surface it exercises.
    * The OTP disclosure uses the HMAC-guarded debug hatch from PR 1
      (`_load_debug_otp_key` + `X-Debug-OTP-Signature`). If the SSM
      debug key is absent the helper raises a clear error explaining
      how to run `scripts/bootstrap-signatures-v2.sh`.
    * A face image is optional. Callers that need `validate_face` in
      the happy path pass `face_path=` OR set `SIGNATURES_TEST_FACE_PATH`
      env var pointing to a real human face JPEG. When missing, only
      the sad-path variant (upload a face-less image, expect 422) is
      possible.

Cleanup: every helper that opens infra returns the sign_id so the
caller can `cleanup_signature(sign_id)` in a `finally` block.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import os
import random
import string
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import requests

from tests.integration_helpers import (
    STAGE,
    _client,
    api_base,
    cleanup_s3_prefix,
    wait_for,
)


# ---------------------------------------------------------------------------
# SSM secrets
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_service_key() -> str:
    """Reads /cdts/{stage}/signatures/service-key (M2M)."""
    resp = _client("ssm").get_parameter(
        Name=f"/cdts/{STAGE}/signatures/service-key",
        WithDecryption=True,
    )
    return resp["Parameter"]["Value"].strip()


@lru_cache(maxsize=1)
def get_debug_otp_key() -> bytes:
    """Reads the debug HMAC key. Raises if the SSM param is missing --
    that is a hard requirement to run these tests."""
    ssm = _client("ssm")
    path = f"/cdts/{STAGE}/signatures/debug-otp-key"
    try:
        resp = ssm.get_parameter(Name=path, WithDecryption=True)
    except ssm.exceptions.ParameterNotFound as e:
        raise RuntimeError(
            f"Missing SSM param {path!r}. This param is required for "
            f"automated OTP disclosure in integration tests. Run "
            f"`bash scripts/bootstrap-signatures-v2.sh --stage {STAGE}` "
            f"with an admin AWS caller to provision it."
        ) from e
    return resp["Parameter"]["Value"].strip().encode()


def hmac_sign_id(sign_id: str) -> str:
    """Computes the X-Debug-OTP-Signature header value for a sign_id."""
    return hmac.new(
        get_debug_otp_key(), sign_id.encode(), hashlib.sha256
    ).hexdigest()


# ---------------------------------------------------------------------------
# Infra shortcuts
# ---------------------------------------------------------------------------
def signatures_api() -> str:
    return api_base("signatures")


def signatures_bucket() -> str:
    return os.environ.get(
        "SIGNATURES_BUCKET", f"cdts-{STAGE}-signatures"
    )


# ---------------------------------------------------------------------------
# Synthetic asset generation
#
# All PIL/reportlab imports are LAZY so a machine without them (rare;
# both are in requirements-dev.txt) can still import this module for
# the ones tests that don't need image generation (upload_url, verify).
# ---------------------------------------------------------------------------
def make_synthetic_pdf(title: str = "INTEGRATION TEST") -> bytes:
    """Minimal single-page PDF the ceremony will sign. Not styled to
    look like anything in particular -- Rekognition never sees it."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 720, title)
    c.setFont("Helvetica", 10)
    c.drawString(72, 690, f"Generated at {datetime.now(timezone.utc).isoformat()}")
    c.drawString(72, 670, "This is a synthetic PDF for integration tests.")
    c.showPage()
    c.save()
    return buf.getvalue()


def make_synthetic_id_png(side: str = "front") -> bytes:
    """PNG that passes Rekognition DetectText for `validate_id_*`.

    Rekognition looks for enough printed text (3+ non-trivial lines +
    a numeric block for the ID number) that a face photo alone would
    fail. Using Pillow with a system font (arial fallback -> default
    bitmap) reliably clears those thresholds.
    """
    from PIL import Image, ImageDraw, ImageFont

    W, H = 640, 400
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (W - 1, H - 1)], outline="black", width=4)

    try:
        font_lg = ImageFont.truetype("arial.ttf", 32)
        font_md = ImageFont.truetype("arial.ttf", 22)
        font_sm = ImageFont.truetype("arial.ttf", 18)
    except (OSError, IOError):
        font_lg = ImageFont.load_default()
        font_md = ImageFont.load_default()
        font_sm = ImageFont.load_default()

    if side == "front":
        lines = [
            ("REPUBLIC OF EXAMPLE", font_lg, 30),
            ("IDENTITY DOCUMENT", font_md, 80),
            ("Number: 1.234.567.890", font_md, 130),
            ("Name: JANE DOE ITEST", font_md, 180),
            ("Born: 15/01/1990   Sex: F", font_sm, 230),
            ("Issued: 2024-06-10", font_sm, 265),
        ]
    else:
        lines = [
            ("BACK OF IDENTITY DOCUMENT", font_lg, 30),
            ("Place of birth: EXAMPLE CITY", font_md, 90),
            ("Height: 165 cm  Blood: O+", font_md, 140),
            ("Signature: [placeholder]", font_sm, 200),
            ("Address: 123 EXAMPLE ST", font_sm, 240),
        ]
    for text, font, y in lines:
        draw.text((30, y), text, fill="black", font=font)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def make_synthetic_signature_png() -> bytes:
    """PNG resembling a hand-drawn signature. `register_signature`
    doesn't validate this cryptographically -- it just needs a
    non-empty PNG under 1MB."""
    from PIL import Image, ImageDraw

    W, H = 600, 200
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rng = random.Random(42)
    points = [
        (
            x,
            int(100 + 30 * (rng.random() - 0.5) + 15 * ((x % 60) - 30) / 30),
        )
        for x in range(20, W - 20, 4)
    ]
    draw.line(points, fill=(20, 20, 90, 255), width=4)
    draw.line(
        [(W - 40, 100), (W - 20, 80), (W - 60, 90), (W - 20, 130)],
        fill=(20, 20, 90, 255),
        width=4,
    )
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def make_faceless_png() -> bytes:
    """Solid-color PNG guaranteed to have zero faces. Used to test the
    sad path of `validate_face` (expected: 422 face_not_found)."""
    from PIL import Image

    img = Image.new("RGB", (400, 400), (128, 128, 128))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def load_face_fixture() -> Optional[bytes]:
    """Loads a real face JPEG from the path stored in the env var
    `SIGNATURES_TEST_FACE_PATH`. Returns None if the env var is
    unset OR the file does not exist. Integration tests that need
    the happy path of `validate_face` should skip if this is None.
    """
    path = os.environ.get("SIGNATURES_TEST_FACE_PATH")
    if not path or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Ceremony context + open_ceremony
# ---------------------------------------------------------------------------
@dataclass
class CeremonyContext:
    """State needed to drive a ceremony after `open_ceremony`."""

    sign_id: str
    hash_original: str
    sign_url: str
    signer_email: str
    signer_name: str
    signatures_bucket: str
    source_key: str  # under signatures_bucket; cleaned up in `close()`
    # Track fresh S3 prefixes for `close()`.
    extra_prefixes: list[str] = field(default_factory=list)

    def close(self) -> None:
        """Deletes the ceremony row + all S3 side effects. Idempotent."""
        # Late import to avoid circular dep.
        from tests.integration_helpers import cleanup_signature

        try:
            cleanup_s3_prefix(self.signatures_bucket, self.source_key)
        except Exception:
            pass
        for pfx in self.extra_prefixes:
            try:
                cleanup_s3_prefix(self.signatures_bucket, pfx)
            except Exception:
                pass
        try:
            cleanup_signature(self.sign_id)
        except Exception:
            pass


def _random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def open_ceremony(
    *,
    signer_email: Optional[str] = None,
    signer_name: str = "Integration Bot",
    signature_location: Optional[dict] = None,
    callback_url: Optional[str] = None,
    pdf_bytes: Optional[bytes] = None,
) -> CeremonyContext:
    """Opens a ceremony end-to-end against dev signatures.

    Uploads a synthetic (or caller-supplied) PDF to the signatures
    bucket, generates a presigned GET, then POSTs `/signatures` with
    the M2M service key. Returns a `CeremonyContext` with everything
    downstream helpers need.

    Caller MUST invoke `ctx.close()` in a `finally` block.
    """
    if signer_email is None:
        signer_email = f"itest-{uuid.uuid4()}@itest.cdts.dev"
    if signature_location is None:
        signature_location = {"page": 1, "x_pct": 10, "y_pct": 10}
    if pdf_bytes is None:
        pdf_bytes = make_synthetic_pdf()

    bucket = signatures_bucket()
    # Under `_test-sources/*` so 30-day lifecycle cleans stragglers.
    source_key = f"_test-sources/{uuid.uuid4()}.pdf"
    s3 = _client("s3")
    s3.put_object(
        Bucket=bucket, Key=source_key, Body=pdf_bytes, ContentType="application/pdf"
    )
    presigned = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": source_key},
        ExpiresIn=300,
    )
    hash_original = hashlib.sha256(pdf_bytes).hexdigest()

    payload: dict = {
        "pdf_source_url": presigned,
        "signature_location": signature_location,
        "signer_email": signer_email,
        "signer_name": signer_name,
        "service_caller": "integration-tests",
    }
    if callback_url:
        payload["callback_url"] = callback_url

    resp = requests.post(
        f"{signatures_api()}/signatures",
        json=payload,
        headers={"X-Service-Key": get_service_key()},
        timeout=30,
    )
    if resp.status_code != 201:
        # Clean up the S3 object we just uploaded; don't leak on error.
        try:
            s3.delete_object(Bucket=bucket, Key=source_key)
        except Exception:
            pass
        raise AssertionError(
            f"POST /signatures failed: {resp.status_code} {resp.text}"
        )
    body = resp.json()
    return CeremonyContext(
        sign_id=body["sign_id"],
        hash_original=body["hash_original"],
        sign_url=body["sign_url"],
        signer_email=signer_email,
        signer_name=signer_name,
        signatures_bucket=bucket,
        source_key=source_key,
    )


# ---------------------------------------------------------------------------
# HTTP helpers scoped to a ceremony
# ---------------------------------------------------------------------------
def upload_evidence(
    ctx: CeremonyContext,
    evidence_type: str,
    body: bytes,
    content_type: str,
) -> str:
    """POSTs `/signatures/{sign_id}/upload-url` then PUTs the bytes to
    the presigned URL. Returns the S3 key that the handler assigned.
    """
    base = signatures_api()
    r = requests.post(
        f"{base}/signatures/{ctx.sign_id}/upload-url",
        json={"evidence_type": evidence_type, "content_type": content_type},
        timeout=30,
    )
    assert r.status_code == 200, f"upload-url {evidence_type} -> {r.status_code} {r.text}"
    data = r.json()
    put = requests.put(
        data["upload_url"],
        data=body,
        headers={"Content-Type": content_type},
        timeout=30,
    )
    assert put.status_code in (200, 204), (
        f"PUT presigned {evidence_type} -> {put.status_code} {put.text}"
    )
    return data["key"]


def validate_id_side(ctx: CeremonyContext, side: str) -> dict:
    """POST /signatures/{sign_id}/validate-id/{side}. Returns the
    parsed response body (200) or raises with the error payload."""
    base = signatures_api()
    r = requests.post(
        f"{base}/signatures/{ctx.sign_id}/validate-id/{side}",
        timeout=60,
    )
    assert r.status_code == 200, f"validate-id/{side} -> {r.status_code} {r.text}"
    return r.json()


def validate_face(ctx: CeremonyContext) -> dict:
    base = signatures_api()
    r = requests.post(
        f"{base}/signatures/{ctx.sign_id}/validate-face", timeout=60
    )
    assert r.status_code == 200, f"validate-face -> {r.status_code} {r.text}"
    return r.json()


def register_signature_drawing(ctx: CeremonyContext) -> dict:
    """After the drawn signature PNG is uploaded, this endpoint marks
    the ceremony's `signature_key` and advances stage when the 4
    evidences are ready. `signature` drawings don't need Rekognition."""
    base = signatures_api()
    r = requests.post(
        f"{base}/signatures/{ctx.sign_id}/register-signature", timeout=30
    )
    assert r.status_code == 200, f"register-signature -> {r.status_code} {r.text}"
    return r.json()


def give_consent(ctx: CeremonyContext, terms_version: str = "v1") -> dict:
    base = signatures_api()
    r = requests.post(
        f"{base}/signatures/{ctx.sign_id}/consent",
        json={"terms_version": terms_version},
        timeout=30,
    )
    assert r.status_code == 200, f"consent -> {r.status_code} {r.text}"
    return r.json()


def request_otp_with_debug_disclosure(ctx: CeremonyContext) -> str:
    """Issues an OTP and returns the plaintext via the HMAC-guarded
    debug hatch. Fails if the SSM debug key is not provisioned."""
    base = signatures_api()
    r = requests.post(
        f"{base}/signatures/{ctx.sign_id}/otp",
        headers={"X-Debug-OTP-Signature": hmac_sign_id(ctx.sign_id)},
        timeout=30,
    )
    assert r.status_code == 200, f"request-otp -> {r.status_code} {r.text}"
    body = r.json()
    otp = body.get("_debug_otp")
    if not otp:
        raise RuntimeError(
            "request_otp did not disclose _debug_otp. Check that "
            f"/cdts/{STAGE}/signatures/debug-otp-key exists AND that "
            "the deployed handler code includes the debug hatch (PR #65 "
            "or its successor)."
        )
    return otp


def verify_otp(ctx: CeremonyContext, otp: str) -> dict:
    base = signatures_api()
    r = requests.post(
        f"{base}/signatures/{ctx.sign_id}/otp/verify",
        json={"otp": otp},
        timeout=30,
    )
    assert r.status_code == 200, f"verify-otp -> {r.status_code} {r.text}"
    return r.json()


def get_ceremony(ctx: CeremonyContext) -> dict:
    base = signatures_api()
    r = requests.get(f"{base}/signatures/{ctx.sign_id}", timeout=30)
    assert r.status_code == 200, f"get ceremony -> {r.status_code} {r.text}"
    return r.json()


def wait_for_stage(
    ctx: CeremonyContext, target_stage: str, timeout_s: float = 90.0
) -> dict:
    """Polls GET /signatures/{sign_id} until stage == target_stage."""

    def _cond():
        state = get_ceremony(ctx)
        if state.get("stage") == target_stage:
            return state
        if state.get("stage") in ("failed", "expired"):
            raise AssertionError(
                f"ceremony landed in terminal state {state.get('stage')!r} "
                f"instead of {target_stage!r}: {state}"
            )
        return None

    result = wait_for(_cond, timeout_s=timeout_s, interval_s=2.0)
    if not result:
        raise AssertionError(
            f"ceremony did not reach stage {target_stage!r} within {timeout_s}s"
        )
    return result


# ---------------------------------------------------------------------------
# High-level "drive to X" flow
# ---------------------------------------------------------------------------
_STAGE_ORDER = ("created", "identity", "consent", "otp", "signing", "signed")


def drive_to_stage(
    ctx: CeremonyContext,
    target: str,
    *,
    face_bytes: Optional[bytes] = None,
) -> dict:
    """Advances the ceremony from its current stage to `target`.

    Callers that don't exercise `validate_face` on the happy path can
    omit `face_bytes` -- the helper will call `load_face_fixture()` and
    skip the face-related steps if no fixture is present, but then it
    cannot advance past 'identity' without one.

    Returns the final ceremony state (GET /signatures/{sign_id}).
    """
    if target not in _STAGE_ORDER:
        raise ValueError(f"unknown target stage: {target!r}")

    # Determine current stage
    state = get_ceremony(ctx)
    if _STAGE_ORDER.index(state["stage"]) >= _STAGE_ORDER.index(target):
        return state

    # Upload evidences + validate up to 'identity'
    if _STAGE_ORDER.index(target) >= _STAGE_ORDER.index("identity") and state["stage"] == "created":
        # id_front + id_back are cheap and required.
        upload_evidence(ctx, "id_front", make_synthetic_id_png("front"), "image/png")
        validate_id_side(ctx, "front")
        upload_evidence(ctx, "id_back", make_synthetic_id_png("back"), "image/png")
        validate_id_side(ctx, "back")

        # Face: use caller-supplied bytes or the env fixture.
        face = face_bytes if face_bytes is not None else load_face_fixture()
        if face is None:
            # Without a real face image, we can't advance past this
            # point. Return whatever state we have; callers must handle.
            return get_ceremony(ctx)
        upload_evidence(ctx, "face", face, "image/jpeg")
        validate_face(ctx)

        # Signature drawing.
        upload_evidence(ctx, "signature", make_synthetic_signature_png(), "image/png")
        register_signature_drawing(ctx)

        state = get_ceremony(ctx)

    if _STAGE_ORDER.index(target) >= _STAGE_ORDER.index("consent") and state["stage"] == "identity":
        give_consent(ctx)
        state = get_ceremony(ctx)

    if _STAGE_ORDER.index(target) >= _STAGE_ORDER.index("otp") and state["stage"] == "consent":
        # request_otp advances stage to 'otp' by itself.
        request_otp_with_debug_disclosure(ctx)
        state = get_ceremony(ctx)

    if _STAGE_ORDER.index(target) >= _STAGE_ORDER.index("signing") and state["stage"] == "otp":
        otp = request_otp_with_debug_disclosure(ctx)  # fresh one
        verify_otp(ctx, otp)
        # verify_otp fires the async `sign` lambda; state may be
        # 'signing' or already 'signed' depending on how fast Lambda
        # picked it up.
        state = get_ceremony(ctx)

    if target == "signed":
        state = wait_for_stage(ctx, "signed", timeout_s=90.0)

    return state
