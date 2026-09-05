import os
import unicodedata
from difflib import SequenceMatcher

import boto3

from utils.http import err, ok, parse_body
from utils.orm.models import DigitalSignatures

BUCKET = os.environ["FILES_BUCKET"]
rek = boto3.client("rekognition")

# Con margen: el OCR puede fallar, basta con que aparezcan MIN de las frases
FRONT_KEYWORDS = ("REPUBLICA DE COLOMBIA", "IDENTIFICACION PERSONAL", "CEDULA DE CIUDADANIA")
FRONT_MIN = 2
BACK_KEYWORDS = ("FECHA DE NACIMIENTO", "LUGAR DE NACIMIENTO", "ESTATURA", "EXPEDICION", "SEXO")
BACK_MIN = 3

VALIDATABLE = ("cedula_front", "cedula_back", "face")


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


def _detect_lines(key: str) -> list[str]:
    r = rek.detect_text(Image={"S3Object": {"Bucket": BUCKET, "Name": key}})
    return [_normalize(t["DetectedText"]) for t in r["TextDetections"] if t["Type"] == "LINE"]


def _matches(lines: list[str], keyword: str) -> bool:
    full = " ".join(lines)
    if keyword in full:
        return True
    if any(SequenceMatcher(None, keyword, ln).ratio() >= 0.7 for ln in lines):
        return True
    tokens = [t for t in keyword.split() if len(t) >= 4]
    return bool(tokens) and all(t in full for t in tokens)


def _score(lines: list[str], keywords: tuple[str, ...]) -> int:
    return sum(1 for k in keywords if _matches(lines, k))


def _has_face(key: str) -> bool:
    r = rek.detect_faces(Image={"S3Object": {"Bucket": BUCKET, "Name": key}})
    return any(f["Confidence"] >= 90 for f in r["FaceDetails"])


def validate(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = DigitalSignatures.get_by_token(token)
    if row is None:
        return err(404, "process_not_found")
    if row.stage == "firmado":
        return err(409, "already_signed")

    body = parse_body(event) or {}
    vtype = body.get("type")
    if vtype not in VALIDATABLE:
        return err(400, "invalid_type")
    key = getattr(row, f"{vtype}_key")
    if not key:
        return err(409, "photo_not_uploaded")

    if vtype == "face":
        valid = _has_face(key)
        reason = "no_face"
    else:
        lines = _detect_lines(key)
        if vtype == "cedula_front":
            valid = _score(lines, FRONT_KEYWORDS) >= FRONT_MIN
            reason = "front_text_not_found"
        else:
            valid = _score(lines, BACK_KEYWORDS) >= BACK_MIN
            reason = "back_text_not_found"

    if valid:
        return ok(200, {"valid": True})

    # Foto rechazada: se descarta y la etapa vuelve a documentos si hace falta
    keys = {t: getattr(row, f"{t}_key") for t in ("cedula_front", "cedula_back", "face", "signature")}
    keys[vtype] = None
    if keys["signature"]:
        stage = "otp"
    elif keys["cedula_front"] and keys["cedula_back"] and keys["face"]:
        stage = "dibujo"
    else:
        stage = "documentos"
    DigitalSignatures.update_by_id(row.id, {f"{vtype}_key": None, "stage": stage})
    return ok(200, {"valid": False, "reason": reason})
