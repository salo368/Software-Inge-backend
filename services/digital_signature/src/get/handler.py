import os

import boto3

from utils.http import err, ok
from utils.orm.models import DigitalSignatures

BUCKET = os.environ["FILES_BUCKET"]
COMMERCE_URL = os.environ["COMMERCE_URL"]
s3 = boto3.client("s3")


def get_process(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = DigitalSignatures.get_by_token(token)
    if row is None:
        return err(404, "process_not_found")

    pdf_url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": BUCKET, "Key": row.pdf_key}, ExpiresIn=900
    )
    local, _, domain = row.email.partition("@")
    return ok(200, {
        "stage": row.stage,
        "cdt_id": row.cdt_id,
        "pdf_url": pdf_url,
        "page": row.page,
        "x": float(row.pos_x),
        "y": float(row.pos_y),
        "email_masked": f"{local[:2]}***@{domain}",
        "uploads": {
            "cedula_front": bool(row.cedula_front_key),
            "cedula_back": bool(row.cedula_back_key),
            "face": bool(row.face_key),
            "signature": bool(row.signature_key),
        },
        "return_url": f"{COMMERCE_URL}/cdt/{row.cdt_id}",
    })
