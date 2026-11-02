"""Validates the back side of the signer's ID document.

Mirrors `validate_id_front.handler` but with a slightly looser
legibility threshold. The back of an ID typically has less text than
the front (a stylized signature, a machine-readable zone, sometimes a
barcode), so requiring the same number of confident LINE detections
rejects legitimate photos.

The two handlers stay separate (instead of one parametric handler) so
each keeps a stable Lambda ARN, IAM binding and CloudWatch namespace;
the shared logic lives in `utils.evidence`.

The signatures service is country-agnostic on purpose, so no keyword
list is baked in -- we just check the photo is legible enough that
Rekognition could pull SOME text out of it.
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


_MIN_LINES = 2
_MIN_CONF = 70.0


def _passes_heuristics(lines: list[dict]) -> tuple[bool, str]:
    confident = [
        line for line in lines if float(line.get("Confidence", 0)) >= _MIN_CONF
    ]
    if len(confident) < _MIN_LINES:
        return False, "too_few_legible_lines"
    return True, "ok"


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]
    ensure_stage_allows(row, ALLOWED_EVIDENCE_STAGES)

    key = resolve_evidence_key(row.sign_id, "id_back")
    evidence_size(key)

    lines = detect_text(key)
    ok, reason = _passes_heuristics(lines)
    if not ok:
        raise HandledError(f"id_back_invalid_{reason}", 422)

    row.attach_evidence("id_back", key)
    row.mark_evidence_validated("id_back")

    return generate_response(
        {
            "sign_id": row.sign_id,
            "stage": row.stage,
            "detected_lines": len(lines),
        }
    )
