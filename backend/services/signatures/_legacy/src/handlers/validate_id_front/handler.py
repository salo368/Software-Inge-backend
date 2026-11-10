"""Validates the front side of the signer's ID document.

Flow (all steps run inside a single warm invocation, ~2-4s including
the Rekognition round trip):

    1. Load the ceremony (require_sign_id) and gate on stage.
    2. Locate the S3 key via `resolve_evidence_key` -- the signer
       already uploaded to this key using a presigned URL returned by
       `upload_url`.
    3. Ask Rekognition to `DetectText` on the S3 reference. No bytes go
       through the lambda.
    4. Apply a language-agnostic legibility heuristic:
         * at least `_MIN_LINES` LINE detections with confidence above
           `_MIN_CONF`, and
         * at least one line containing a run of digits typical of an
           ID (>= `_MIN_DIGIT_RUN` characters).
       This is intentionally lenient -- our goal is to reject blurry
       or blank uploads, not to authoritatively identify the person or
       the ID type. Downstream signing (OTP + PAdES + evidence
       package) is what carries legal weight.
    5. On success, attach the key and stamp `_validated_at`.

The signatures service is country-agnostic on purpose, so no keyword
list (e.g. "REPUBLICA DE COLOMBIA", "PASSPORT", ...) is baked in.

Failure modes:

    * evidence_missing              -> 404, nothing at the expected key
    * evidence_too_large            -> 413, over Rekognition's 5 MiB cap
    * id_front_invalid_*            -> 422, heuristics rejected content
    * stage_not_allowed_current_*   -> 409/410, already signed or past OTP
"""

from __future__ import annotations

from libs.core.responses import HandledError, generate_response, handle_exceptions

from utils.auth import ensure_stage_allows, require_sign_id
from utils.evidence import (
    ALLOWED_EVIDENCE_STAGES,
    detect_text,
    evidence_size,
    resolve_evidence_key,
)


# Legibility thresholds. Deliberately loose: the front of an ID has a
# name line, some labels, a photo caption and the ID number; requiring
# more than a few legible LINEs starts rejecting real photos taken
# under bad light.
_MIN_LINES = 3
_MIN_CONF = 70.0
# Most national IDs, passports and driver licenses show a numeric code
# somewhere on the front. Real-world OCR often splits it with dots,
# spaces, or slashes ("1.234.567.890", "A-123 456"), so instead of
# requiring a single contiguous run we count total digits across the
# whole detected text.
_MIN_TOTAL_DIGITS = 6


def _count_digits(text: str) -> int:
    return sum(1 for c in text if c.isdigit())


def _passes_heuristics(lines: list[dict]) -> tuple[bool, str]:
    """Returns (ok, reason). `reason` is stable enough for the UI to
    map to a human message; when ok=True it's 'ok'."""
    confident = [
        line for line in lines if float(line.get("Confidence", 0)) >= _MIN_CONF
    ]
    if len(confident) < _MIN_LINES:
        return False, "too_few_legible_lines"

    total_digits = sum(
        _count_digits(line.get("DetectedText", "")) for line in confident
    )
    if total_digits < _MIN_TOTAL_DIGITS:
        return False, "no_id_number_detected"
    return True, "ok"


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]
    ensure_stage_allows(row, ALLOWED_EVIDENCE_STAGES)

    key = resolve_evidence_key(row.sign_id, "id_front")
    evidence_size(key)  # 413 guard before we call Rekognition

    lines = detect_text(key)
    ok, reason = _passes_heuristics(lines)
    if not ok:
        raise HandledError(f"id_front_invalid_{reason}", 422)

    row.attach_evidence("id_front", key)
    row.mark_evidence_validated("id_front")

    return generate_response(
        {
            "sign_id": row.sign_id,
            "stage": row.stage,
            "detected_lines": len(lines),
        }
    )
