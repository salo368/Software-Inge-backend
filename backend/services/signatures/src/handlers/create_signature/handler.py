import base64
import os
import time
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import upload_from_bytes
from libs.orm.signatures import Signatures

BUCKET = os.environ["SIGNATURES_BUCKET"]


def _uuid7() -> UUID:
    """RFC 9562 UUIDv7: 48-bit ms timestamp + version/variant + random.
    Time-ordered, unlike `uuid4` -- used for the S3 key, not the row id."""

    unix_ts_ms = int(time.time() * 1000)
    rand = os.urandom(10)

    ts_bytes = unix_ts_ms.to_bytes(6, "big")

    rand_a = int.from_bytes(rand[0:2], "big") & 0x0FFF
    rand_b = int.from_bytes(rand[2:10], "big") & 0x3FFFFFFFFFFFFFFF

    byte6 = 0x70 | (rand_a >> 8)
    byte7 = rand_a & 0xFF
    byte8 = 0x80 | (rand_b >> 56)
    rest = (rand_b & 0x00FFFFFFFFFFFFFF).to_bytes(7, "big")

    return UUID(bytes=ts_bytes + bytes([byte6, byte7, byte8]) + rest)


@handle_exceptions
def handler(event, context):

    body = event.get("body") or ""

    if event.get("isBase64Encoded"):
        file_bytes = base64.b64decode(body)
    else:
        file_bytes = body.encode("utf-8") if isinstance(body, str) else body

    if not file_bytes:
        raise HandledError("a file is required", 400)

    doc_s3_key = f"{_uuid7()}.pdf"

    upload_from_bytes(BUCKET, doc_s3_key, file_bytes, content_type="application/pdf")

    row = Signatures.create(doc_s3_key)

    response = {
        "id": row.id,
        "stage": row.stage,
        "doc_s3_key": row.doc_s3_key,
        "sign_location": row.sign_location,
    }

    return generate_response(response, 200)
