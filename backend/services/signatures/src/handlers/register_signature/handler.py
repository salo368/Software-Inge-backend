"""Registers the drawn signature canvas after the microfront uploaded it.

Unlike the other three evidence handlers, this one does NOT call
Rekognition -- a hand-drawn signature is not a natural image and would
score poorly on `DetectText` / `DetectFaces` anyway. We just verify:

    * the object exists at the expected key;
    * it's a real PNG (magic bytes check on the first 8 bytes);
    * it's between `_MIN_BYTES` (rejects an empty canvas) and the
      shared evidence size cap (rejects a 5 MiB screenshot).

Then we attach the key to the ceremony. The ORM's `attach_evidence`
advances stage to `identity` (if still `created`) or leaves it at
whatever `resolved_stage()` computes -- once all four evidences are
in and the three biometric ones are validated, `all_evidences_ready`
becomes True and the frontend can transition to consent.

Failure modes:

    * evidence_missing              -> 404
    * evidence_too_large            -> 413
    * signature_invalid_not_png     -> 422
    * signature_invalid_empty       -> 422
    * stage_not_allowed_current_*   -> 409/410
"""

from __future__ import annotations

from libs.core.responses import HandledError, generate_response, handle_exceptions

from utils.auth import ensure_stage_allows, require_sign_id
from utils.evidence import (
    ALLOWED_EVIDENCE_STAGES,
    evidence_size,
    get_evidence_bytes,
    looks_like_png,
    resolve_evidence_key,
)


# A blank canvas exported by browsers is a few hundred bytes; a real
# signature drawing is typically 5-100 KB. 1 KiB cleanly rejects the
# empty case without borderline false positives.
_MIN_BYTES = 1024


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]
    ensure_stage_allows(row, ALLOWED_EVIDENCE_STAGES)

    key = resolve_evidence_key(row.sign_id, "signature")
    size = evidence_size(key)
    if size < _MIN_BYTES:
        raise HandledError("signature_invalid_empty", 422)

    # We do fetch bytes here, unlike the biometric handlers: the PNG
    # magic-byte check requires the first 8 bytes, and pulling them via
    # a Range GET saves nothing (S3 charges per request, not per byte).
    data = get_evidence_bytes(key)
    if not looks_like_png(data):
        raise HandledError("signature_invalid_not_png", 422)

    row.attach_evidence("signature", key)

    return generate_response(
        {
            "sign_id": row.sign_id,
            "stage": row.stage,
            "bytes": size,
        }
    )
