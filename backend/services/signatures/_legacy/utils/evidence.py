"""Shared helpers for the four evidence handlers under
`/signatures/{sign_id}/evidence/*`.

Every evidence lambda follows the same skeleton:

    1. Locate the S3 object that the client uploaded via `upload_url`
       (deterministic key layout, so no extra client payload is needed).
    2. Validate it (Rekognition for biometric evidence, header + size
       check for the drawn signature).
    3. Persist the key + validation timestamp on the ceremony row.

This module owns steps (1) and shared bits of (2). Each handler keeps
its own validator on top so behaviour stays legible.

Key layout (must stay in sync with `handlers/upload_url/handler.py`):

    transactions/{sign_id}/id/front.{jpg|png}
    transactions/{sign_id}/id/back.{jpg|png}
    transactions/{sign_id}/face.{jpg|png}
    transactions/{sign_id}/signature.png

For images we try `.jpg` before `.png` because that's what browsers
default to when re-encoding a canvas or a phone camera; the drawn
signature is a pure alpha canvas so only `.png` is accepted upstream.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from libs.core.responses import HandledError


SIGNATURES_BUCKET = os.environ["SIGNATURES_BUCKET"]

# Rekognition caps images at 5 MiB per request. We leave headroom so the
# upload can be slightly over the wire size (headers, base64) and still
# fit. Anything above this is rejected before we call AWS.
_MAX_EVIDENCE_BYTES = 5 * 1024 * 1024

# evidence_type -> (S3 prefix under transactions/{sign_id}/,
#                   candidate extensions in preference order).
_PROBE_MAP: dict[str, Tuple[str, Tuple[str, ...]]] = {
    "id_front":  ("id/front",  ("jpg", "png")),
    "id_back":   ("id/back",   ("jpg", "png")),
    "face":      ("face",      ("jpg", "png")),
    "signature": ("signature", ("png",)),
}


def _s3():
    # A fresh client per call is fine: boto3 caches the underlying
    # connection pool in the module-level session, so the cost is just
    # a dict lookup after the first call.
    return boto3.client("s3")


def resolve_evidence_key(sign_id: str, evidence_type: str) -> str:
    """Locates the S3 key uploaded via `upload_url` for this evidence.

    Probes each candidate extension in order and returns the first that
    exists. Raises `HandledError('evidence_missing', 404)` when nothing
    is there yet -- the signer probably skipped the upload step or the
    presigned PUT failed silently.
    """
    if evidence_type not in _PROBE_MAP:
        # Programming error, not user input. Fail loud so the handler
        # test catches it in CI instead of a mysterious 404 in prod.
        raise ValueError(f"unknown evidence type {evidence_type!r}")

    prefix, extensions = _PROBE_MAP[evidence_type]
    s3 = _s3()
    for ext in extensions:
        key = f"transactions/{sign_id}/{prefix}.{ext}"
        try:
            s3.head_object(Bucket=SIGNATURES_BUCKET, Key=key)
            return key
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            # boto3 surfaces missing S3 objects as either "NotFound" or
            # "404"; either way we treat it as "try the next extension".
            if code in ("NotFound", "404") or status == 404:
                continue
            # Any other error (permissions, throttling, ...) escalates.
            raise
    raise HandledError("evidence_missing", 404)


def evidence_size(key: str) -> int:
    """Returns the S3 object size in bytes for `key`. Raises
    `HandledError('evidence_too_large', 413)` when above the Rekognition
    cap so the handler short-circuits before calling AWS."""
    s3 = _s3()
    head = s3.head_object(Bucket=SIGNATURES_BUCKET, Key=key)
    size = int(head["ContentLength"])
    if size > _MAX_EVIDENCE_BYTES:
        raise HandledError("evidence_too_large", 413)
    return size


def get_evidence_bytes(key: str) -> bytes:
    """Downloads the raw bytes for `key`. Used by validators that can't
    operate on an S3 reference (e.g. PNG header checks for the drawn
    signature). Size cap is enforced by `evidence_size` first."""
    evidence_size(key)
    s3 = _s3()
    obj = s3.get_object(Bucket=SIGNATURES_BUCKET, Key=key)
    return obj["Body"].read()


def s3_ref(key: str) -> dict:
    """Rekognition-compatible `Image` payload for an S3 object.

    Rekognition supports either `Bytes` or `S3Object`; the S3Object mode
    is cheaper (no bytes through the lambda) and works with the same
    IAM permissions we already have on the signatures bucket.
    """
    return {"S3Object": {"Bucket": SIGNATURES_BUCKET, "Name": key}}


# ---------------------------------------------------------------------------
# Rekognition wrappers
# ---------------------------------------------------------------------------
def _rekog():
    return boto3.client("rekognition")


def detect_text(key: str) -> list[dict]:
    """Returns the list of LINE-type text detections for an ID photo.

    We ignore WORD-type detections; the heuristic upstream just wants to
    know whether the photo is legible enough to be an ID at all, and
    that's easier to reason about at LINE granularity.
    """
    resp = _rekog().detect_text(Image=s3_ref(key))
    return [
        d for d in resp.get("TextDetections", []) if d.get("Type") == "LINE"
    ]


def detect_faces(key: str) -> list[dict]:
    """Returns the list of FaceDetail entries for a selfie.

    We request the EYES_OPEN attribute explicitly. Rekognition's
    `DEFAULT` bundle only returns BoundingBox, Confidence, Pose,
    Quality and Landmarks -- NOT EyesOpen -- so
    `validate_face._passes_heuristics` would always short-circuit
    into `eyes_closed` because `EyesOpen.Value` would be missing
    (None) even for wide-open eyes. Requesting the specific
    attribute is cheaper than ALL and keeps the response small.
    """
    resp = _rekog().detect_faces(Image=s3_ref(key), Attributes=["EYES_OPEN"])
    return resp.get("FaceDetails", [])


# ---------------------------------------------------------------------------
# Simple validators
# ---------------------------------------------------------------------------
def looks_like_png(data: bytes) -> bool:
    """Cheap PNG signature check for the drawn signature canvas."""
    return data[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Stage sets shared by the four evidence handlers
# ---------------------------------------------------------------------------
# Any evidence step accepts these ceremony stages. We allow re-validation
# from `identity` (some evidences already attached) and even from
# `consent` (all validated, but the signer wants to redo one before OTP).
# Terminal states (`signed`, `expired`, `failed`) are rejected earlier
# by `ensure_stage_allows`.
ALLOWED_EVIDENCE_STAGES: Tuple[str, ...] = ("created", "identity", "consent")
