"""Checks an uploaded photo with Rekognition before it counts as evidence.

OCR is noisy, so a document passes on a quorum of expected phrases rather
than all of them, and each phrase also matches fuzzily. A rejected photo is
detached, which rolls the ceremony back to whatever stage the remaining
evidence supports.
"""
import json
import os
import unicodedata
from difflib import SequenceMatcher

import boto3

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.signatures import Signatures

BUCKET = os.environ["FILES_BUCKET"]
_rekognition = boto3.client("rekognition")

FRONT_KEYWORDS = ("REPUBLICA DE COLOMBIA", "IDENTIFICACION PERSONAL", "CEDULA DE CIUDADANIA")
FRONT_QUORUM = 2
BACK_KEYWORDS = ("FECHA DE NACIMIENTO", "LUGAR DE NACIMIENTO", "ESTATURA", "EXPEDICION", "SEXO")
BACK_QUORUM = 3
FACE_MIN_CONFIDENCE = 90

VALIDATABLE = ("cedula_front", "cedula_back", "face")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.upper().split())


def _detected_lines(key: str) -> list[str]:
    resp = _rekognition.detect_text(Image={"S3Object": {"Bucket": BUCKET, "Name": key}})
    return [_normalize(d["DetectedText"]) for d in resp["TextDetections"] if d["Type"] == "LINE"]


def _matches(lines: list[str], keyword: str) -> bool:
    joined = " ".join(lines)
    if keyword in joined:
        return True
    if any(SequenceMatcher(None, keyword, line).ratio() >= 0.7 for line in lines):
        return True
    tokens = [t for t in keyword.split() if len(t) >= 4]
    return bool(tokens) and all(t in joined for t in tokens)


def _quorum(lines: list[str], keywords: tuple[str, ...]) -> int:
    return sum(1 for k in keywords if _matches(lines, k))


def _has_face(key: str) -> bool:
    resp = _rekognition.detect_faces(Image={"S3Object": {"Bucket": BUCKET, "Name": key}})
    return any(f["Confidence"] >= FACE_MIN_CONFIDENCE for f in resp["FaceDetails"])


@handle_exceptions
def handler(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = Signatures.get_by_token(token)
    if row is None:
        raise HandledError("signature_not_found", 404)
    if row.stage == "signed":
        raise HandledError("already_signed", 409)

    body = json.loads(event.get("body") or "{}")
    evidence_type = body.get("type")
    if evidence_type not in VALIDATABLE:
        raise HandledError(f"type must be one of {sorted(VALIDATABLE)}", 400)

    key = getattr(row, f"{evidence_type}_key")
    if not key:
        raise HandledError("photo_not_uploaded", 409)

    if evidence_type == "face":
        valid = _has_face(key)
    else:
        lines = _detected_lines(key)
        if evidence_type == "cedula_front":
            valid = _quorum(lines, FRONT_KEYWORDS) >= FRONT_QUORUM
        else:
            valid = _quorum(lines, BACK_KEYWORDS) >= BACK_QUORUM

    if not valid:
        row.attach_evidence(evidence_type, None)

    return generate_response({"valid": valid, "stage": row.stage})
