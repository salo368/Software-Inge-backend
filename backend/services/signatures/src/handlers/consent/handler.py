"""Captures the signer's explicit consent to sign.

Rationale: Ley 527/1999 (and analogous e-signature laws in most
jurisdictions) treats "authentication" and "expression of consent" as
two distinct events that must be separately auditable. Uploading a
selfie and an ID authenticates the signer; clicking "I agree, sign
this document" expresses consent. The audit trail must show both, in
order, with timestamps.

Flow:

    1. Load ceremony (require_sign_id).
    2. Reject if the ceremony is in a stage where consent doesn't
       apply: 'created' (no evidence yet) and 'identity' (partial
       evidence) hit `all_evidences_ready`=False and get a 409.
       'consent' means the signer already consented; we accept as
       idempotent (re-clicking the button should not error).
       Terminal states are rejected earlier by ensure_stage_allows.
    3. Body validation: `terms_version` is required and must be a
       known version string; unknown versions get 400 so the frontend
       can pull the current one via GET /signatures/{sign_id} and
       retry.
    4. Call `row.give_consent(terms_version)` which stamps
       `consent_given_at` and moves stage to 'consent'.

Failure modes:

    * missing_terms_version   -> 400
    * unknown_terms_version   -> 400
    * evidence_not_complete   -> 409 (ORM's ValueError -> HandledError)
"""

from __future__ import annotations

import json

from libs.core.responses import HandledError, generate_response, handle_exceptions

from utils.auth import ensure_stage_allows, require_sign_id


# Versions of the consent text that this Lambda accepts. The frontend
# pins its own copy to one of these strings and echoes it back in the
# consent payload; that way the audit trail records EXACTLY which
# wording the signer saw.
#
# Adding a version means editing this tuple AND publishing the new
# text on the microfront. The old versions stay accepted forever so
# historical ceremonies keep validating.
_KNOWN_TERMS_VERSIONS = ("v1.0",)

_ALLOWED_STAGES = ("identity", "consent")


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]
    ensure_stage_allows(row, _ALLOWED_STAGES)

    body = json.loads(event.get("body") or "{}")
    terms_version = body.get("terms_version")
    if not terms_version or not isinstance(terms_version, str):
        raise HandledError("missing_terms_version", 400)
    if terms_version not in _KNOWN_TERMS_VERSIONS:
        raise HandledError("unknown_terms_version", 400)

    # Idempotence: if consent was already given, re-running with the
    # SAME terms_version is a no-op; changing versions is not allowed
    # because the audit trail would then have two conflicting entries.
    if row.consent_given_at is not None:
        if row.consent_terms_version != terms_version:
            raise HandledError("consent_terms_version_mismatch", 409)
    else:
        try:
            row.give_consent(terms_version)
        except ValueError:
            # ORM raises when all_evidences_ready is False (not every
            # evidence is validated yet). Surface a stable code so the
            # frontend can go back to the wizard.
            raise HandledError("evidence_not_complete", 409)

    return generate_response(
        {
            "sign_id": row.sign_id,
            "stage": row.stage,
            "consent": {
                "given_at": row.consent_given_at.isoformat(),
                "terms_version": row.consent_terms_version,
            },
        }
    )
