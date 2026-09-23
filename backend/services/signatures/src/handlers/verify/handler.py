"""Public PAdES verification endpoint (POST /signatures/verify).

Anyone can call this: no service key, no sign_id capability. The
signed PDF is either fetched from a caller-supplied URL or from our
own signatures bucket by sign_id.

The verification itself is delegated to `utils.mock_ca.verify_pades_pdf`
which:

    * parses the PDF and extracts the embedded PAdES signature,
    * checks document integrity (bytes intact vs signed hash),
    * checks signature validity (RSA over the signed hash),
    * builds the cert chain against the mock CA root from SSM.

    15|Result dict shape (returned to the caller, verbatim from mock_ca):

    {
        "valid": bool,                # overall pass/fail
        "document_integrity": bool,   # bytes intact
        "signature_valid": bool,      # signature verifies vs cert
        "certificate_valid": bool,    # chain reaches our root
        "signer_email": str | None,
        "signer_name": str | None,
        "cert_serial": str | None,
        "signed_at": str | None,
        "reason": str | None,         # non-empty if not valid
    }

We enrich this with a "ceremony" section if `cert_serial` maps to a
signatures.Signatures row -- consent metadata + created_at + a masked
sign_id (first 6 chars) so the auditor can cross-reference the run
without leaking the capability token in full.

Input shape (choose exactly ONE):

    {"pdf_source_url": "https://..."}  # download and verify any PDF
    {"sign_id":        "..."}          # verify our own signed.pdf

Error codes:

    invalid_body                 -> 400
    could_not_download_source_pdf -> 400 (URL variant)
    unknown_sign_id              -> 404 (sign_id variant)
    ceremony_not_signed          -> 404 (sign_id variant, no signed.pdf yet)
"""

from __future__ import annotations

import json
import os
from typing import Optional

import boto3
import requests

from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.signatures import Signatures

from utils.mock_ca import verify_pades_pdf


SIGNATURES_BUCKET = os.environ["SIGNATURES_BUCKET"]

# Same short window as `create` -- callers should be pointing at
# presigned URLs or plain https objects, both of which resolve fast.
_DOWNLOAD_TIMEOUT_S = 15

# Defensive cap on payload the verifier will process. `verify_pades_pdf`
# holds the full byte string in memory, and the API Gateway payload we
# pass to it also travels the wire. 25 MiB is generous for typical
# signed contracts and rejects an accidental multi-gig object early.
_MAX_PDF_BYTES = 25 * 1024 * 1024


def _load_pdf_from_url(url: str) -> bytes:
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise HandledError("invalid_pdf_source_url", 400)
    try:
        resp = requests.get(url, timeout=_DOWNLOAD_TIMEOUT_S, stream=True)
        resp.raise_for_status()
        # Stream + cap so a malicious server can't hand us a 5 GB blob.
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MAX_PDF_BYTES:
                raise HandledError("source_pdf_too_large", 413)
            chunks.append(chunk)
    except HandledError:
        raise
    except requests.RequestException as e:
        Logger.log("WARNING", f"verify: could not download pdf: {e}")
        raise HandledError("could_not_download_source_pdf", 400)

    return b"".join(chunks)


def _load_pdf_from_sign_id(sign_id: str) -> tuple[bytes, Signatures]:
    """Fetches our own signed.pdf. Also returns the row so the caller
    can decide whether the ceremony is even in a state where a signed
    PDF exists."""
    if not isinstance(sign_id, str) or not sign_id:
        raise HandledError("invalid_sign_id", 400)
    row = Signatures.get_by_sign_id(sign_id)
    if row is None:
        raise HandledError("unknown_sign_id", 404)
    if row.stage != "signed":
        raise HandledError("ceremony_not_signed", 404)

    # evidence-archive/, not transactions/ -- see sign/handler.py module
    # docstring (10-year retention prefix split).
    key = f"evidence-archive/{sign_id}/signed.pdf"
    try:
        obj = boto3.client("s3").get_object(Bucket=SIGNATURES_BUCKET, Key=key)
        # S3 object metadata carries ContentLength; check it before we
        # read the body so we don't page a huge blob into memory.
        if obj.get("ContentLength", 0) > _MAX_PDF_BYTES:
            raise HandledError("signed_pdf_too_large", 413)
        return obj["Body"].read(), row
    except HandledError:
        raise
    except Exception as e:
        Logger.log("ERROR", f"verify: could not fetch signed.pdf: {e}")
        raise HandledError("could_not_read_signed_pdf", 500)


def _mask_email(email: Optional[str]) -> Optional[str]:
    """Same masking rule as Signatures.masked_email; kept local so we can
    apply it to the cert's SubjectAltName email even when there is no
    matching row in the DB (external verifier bringing their own PDF)."""
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"


def _ceremony_context(row: Optional[Signatures]) -> Optional[dict]:
    if row is None:
        return None
    return {
        # First 6 chars only: enough for support to grep, doesn't leak
        # the full capability token to an anonymous caller.
        "sign_id_short": row.sign_id[:6],
        "stage": row.stage,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "signed_at": row.signed_at.isoformat() if row.signed_at else None,
        "consent": {
            "given_at": (
                row.consent_given_at.isoformat() if row.consent_given_at else None
            ),
            "terms_version": row.consent_terms_version,
        },
        "hash_original": row.hash_original,
        "hash_signed": row.hash_signed,
        "service_caller": row.service_caller,
    }


@handle_exceptions
def handler(event, context):
    body = json.loads(event.get("body") or "{}")

    pdf_source_url = body.get("pdf_source_url")
    sign_id = body.get("sign_id")

    if (pdf_source_url is None) == (sign_id is None):
        # Both provided OR both missing. Force the caller to choose one
        # mode explicitly; otherwise the response contract is ambiguous
        # (whose ceremony context wins?).
        raise HandledError("invalid_body_provide_one_of_pdf_source_url_or_sign_id", 400)

    known_row: Optional[Signatures] = None
    if pdf_source_url is not None:
        pdf_bytes = _load_pdf_from_url(pdf_source_url)
    else:
        pdf_bytes, known_row = _load_pdf_from_sign_id(sign_id)

    result = verify_pades_pdf(pdf_bytes)

    # If the caller passed a URL, we don't know a priori which ceremony
    # (if any) issued the leaf cert -- look it up by cert_serial. When
    # the sign_id path was used, `known_row` is authoritative and we
    # skip the DB round-trip.
    ceremony_row = known_row
    if ceremony_row is None and result.get("cert_serial"):
        ceremony_row = Signatures.get_by_cert_serial(result["cert_serial"])

    response = {
        "valid": result["valid"],
        "document_integrity": result["document_integrity"],
        "signature_valid": result["signature_valid"],
        "certificate_valid": result["certificate_valid"],
        "signer": {
            "email_masked": _mask_email(result.get("signer_email")),
            "name": result.get("signer_name"),
        },
        "cert_serial": result.get("cert_serial"),
        "signed_at": result.get("signed_at"),
        "reason": result.get("reason"),
        "ceremony": _ceremony_context(ceremony_row),
    }
    return generate_response(response)
