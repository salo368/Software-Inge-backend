"""Validates the signer's selfie.

Flow:

    1. Load the ceremony and gate on stage.
    2. Resolve the S3 key for the face slot (jpg or png).
    3. Rekognition `DetectFaces` on the S3 reference.
    4. Heuristic:
         * exactly one face detected (multi-face photos are suspicious
           and hard to bind to a signer identity);
         * confidence above `_MIN_CONFIDENCE` (Rekognition is generous
           here, so 90 is safe);
         * eyes reasonably open (`EyesOpen.Value=True` and
           `EyesOpen.Confidence >= _EYES_MIN_CONF`), to reject the
           common failure mode of "user uploaded a photo of a photo of
           an ID card".
    5. Attach the key and stamp `_validated_at`.

Failure modes:

    * evidence_missing              -> 404
    * evidence_too_large            -> 413
    * face_invalid_no_face_detected -> 422
    * face_invalid_multiple_faces   -> 422
    * face_invalid_low_confidence   -> 422
    * face_invalid_eyes_closed      -> 422
"""

from __future__ import annotations

from libs.core.responses import HandledError, generate_response, handle_exceptions

from utils.auth import ensure_stage_allows, require_sign_id
from utils.evidence import (
    ALLOWED_EVIDENCE_STAGES,
    detect_faces,
    evidence_size,
    resolve_evidence_key,
)


_MIN_CONFIDENCE = 90.0
_EYES_MIN_CONF = 80.0


def _passes_heuristics(faces: list[dict]) -> tuple[bool, str]:
    if len(faces) == 0:
        return False, "no_face_detected"
    if len(faces) > 1:
        return False, "multiple_faces"

    (face,) = faces
    if float(face.get("Confidence", 0)) < _MIN_CONFIDENCE:
        return False, "low_confidence"

    eyes = face.get("EyesOpen") or {}
    eyes_open = bool(eyes.get("Value"))
    eyes_conf = float(eyes.get("Confidence", 0))
    if not eyes_open or eyes_conf < _EYES_MIN_CONF:
        return False, "eyes_closed"

    return True, "ok"


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]
    ensure_stage_allows(row, ALLOWED_EVIDENCE_STAGES)

    key = resolve_evidence_key(row.sign_id, "face")
    evidence_size(key)

    faces = detect_faces(key)
    ok, reason = _passes_heuristics(faces)
    if not ok:
        raise HandledError(f"face_invalid_{reason}", 422)

    row.attach_evidence("face", key)
    row.mark_evidence_validated("face")

    return generate_response(
        {
            "sign_id": row.sign_id,
            "stage": row.stage,
        }
    )
