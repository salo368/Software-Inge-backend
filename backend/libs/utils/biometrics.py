"""Biometric evidence validators for the signatures BIOMETRICS stage.

Each `analyze_*` function takes the bucket and S3 key the front already
uploaded to (via a presigned PUT from `upload_biometrics`) and returns
(is_valid, reason) -- never raises for a bad photo, since a failed
validation is a normal outcome `set_biometrics` reports back to the
front, not a server error.

Ported from the Rekognition heuristics in
services/signatures/_legacy/utils/evidence.py, simplified to a single
known S3 key per call (the new flow already knows exactly where it
uploaded to, so there's no need to probe candidate extensions).
"""
from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

# Rekognition caps images at 5 MiB per request.
_MAX_EVIDENCE_BYTES = 5 * 1024 * 1024

# Legibility thresholds -- deliberately loose: real-world photos taken
# under bad light shouldn't get rejected for being short a line or two.
_MIN_ID_FRONT_LINES = 3
_MIN_ID_BACK_LINES = 2
_MIN_LINE_CONFIDENCE = 70.0
_MIN_ID_FRONT_TOTAL_DIGITS = 6

_MIN_FACE_CONFIDENCE = 90.0
_MIN_EYES_OPEN_CONFIDENCE = 80.0


def _s3():
    return boto3.client("s3")


def _rekognition():
    return boto3.client("rekognition")


def _s3_ref(bucket: str, key: str) -> dict:
    return {"S3Object": {"Bucket": bucket, "Name": key}}


def _check_size(bucket: str, key: str) -> tuple[bool, str] | None:
    """Returns an early (False, reason) if the object is missing or too
    large for Rekognition; None means "fine, keep going"."""
    try:
        head = _s3().head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in ("NotFound", "404") or status == 404:
            return False, "evidence_missing"
        raise
    if int(head["ContentLength"]) > _MAX_EVIDENCE_BYTES:
        return False, "evidence_too_large"
    return None


def _count_digits(text: str) -> int:
    return sum(1 for c in text if c.isdigit())


def _detect_text_lines(bucket: str, key: str) -> list[dict]:
    resp = _rekognition().detect_text(Image=_s3_ref(bucket, key))
    return [d for d in resp.get("TextDetections", []) if d.get("Type") == "LINE"]


def analyze_id_front(bucket: str, key: str) -> tuple[bool, str]:
    size_issue = _check_size(bucket, key)
    if size_issue:
        return size_issue

    lines = _detect_text_lines(bucket, key)
    confident = [l for l in lines if float(l.get("Confidence", 0)) >= _MIN_LINE_CONFIDENCE]
    if len(confident) < _MIN_ID_FRONT_LINES:
        return False, "too_few_legible_lines"

    total_digits = sum(_count_digits(l.get("DetectedText", "")) for l in confident)
    if total_digits < _MIN_ID_FRONT_TOTAL_DIGITS:
        return False, "no_id_number_detected"

    return True, "ok"


def analyze_id_back(bucket: str, key: str) -> tuple[bool, str]:
    size_issue = _check_size(bucket, key)
    if size_issue:
        return size_issue

    lines = _detect_text_lines(bucket, key)
    confident = [l for l in lines if float(l.get("Confidence", 0)) >= _MIN_LINE_CONFIDENCE]
    if len(confident) < _MIN_ID_BACK_LINES:
        return False, "too_few_legible_lines"

    return True, "ok"


def analyze_face(bucket: str, key: str) -> tuple[bool, str]:
    size_issue = _check_size(bucket, key)
    if size_issue:
        return size_issue

    resp = _rekognition().detect_faces(Image=_s3_ref(bucket, key), Attributes=["EYES_OPEN"])
    faces = resp.get("FaceDetails", [])

    if len(faces) == 0:
        return False, "no_face_detected"
    if len(faces) > 1:
        return False, "multiple_faces"

    (face,) = faces
    if float(face.get("Confidence", 0)) < _MIN_FACE_CONFIDENCE:
        return False, "low_confidence"

    eyes = face.get("EyesOpen") or {}
    eyes_open = bool(eyes.get("Value"))
    eyes_confidence = float(eyes.get("Confidence", 0))
    if not eyes_open or eyes_confidence < _MIN_EYES_OPEN_CONFIDENCE:
        return False, "eyes_closed"

    return True, "ok"
