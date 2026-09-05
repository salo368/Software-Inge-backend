import os

import boto3

from utils.http import err, ok, parse_body
from utils.orm.models import DigitalSignatures

BUCKET = os.environ["FILES_BUCKET"]
s3 = boto3.client("s3")

TYPES = ("cedula_front", "cedula_back", "face", "signature")
EXT = {"image/jpeg": "jpg", "image/png": "png"}


def upload_url(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = DigitalSignatures.get_by_token(token)
    if row is None:
        return err(404, "process_not_found")
    if row.stage == "firmado":
        return err(409, "already_signed")

    body = parse_body(event) or {}
    ftype = body.get("type")
    ctype = body.get("content_type", "image/jpeg")
    if ftype not in TYPES or ctype not in EXT:
        return err(400, "invalid_type")

    key = f"processes/{token}/{ftype}.{EXT[ctype]}"
    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": ctype},
        ExpiresIn=900,
    )

    uploads = {t: getattr(row, f"{t}_key") for t in TYPES}
    uploads[ftype] = key
    if uploads["signature"]:
        stage = "otp"
    elif uploads["cedula_front"] and uploads["cedula_back"] and uploads["face"]:
        stage = "dibujo"
    else:
        stage = "documentos"

    DigitalSignatures.update_by_id(row.id, {f"{ftype}_key": key, "stage": stage})
    return ok(200, {"upload_url": url, "key": key, "stage": stage})
