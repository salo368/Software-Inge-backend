"""Mock Certification Authority for the signatures service.

Models the certification-entity actor from `docs/arquitectura_firma_digital_
colombia_resumen.md` §3: the root of trust that owns the CA private key
and issues certificates. Deliberately isolated behind a small function
API (`issue_transaction_cert`, `sign_pdf_pades_b`, `verify_pades_pdf`)
so a future integration with a real CA (Certicámara, Andes SCD, GSE)
can replace this module without touching the ceremony code.

Trust model (Ley 527/1999 chain, mocked):

    /cdts/{stage}/mock-ca/root/cert-pem        <-- SSM SecureString KMS
    /cdts/{stage}/mock-ca/root/private-key-pem <-- SSM SecureString KMS

    root CA cert + private key (bootstrapped manually per stage; see
    docs/signatures-v2.md for the openssl commands)
           |
           | signs
           v
    ephemeral leaf cert (per transaction, 1h validity)
    private key lives ONLY in the invoking Lambda's memory for the
    duration of the `sign` call; never written anywhere.
           |
           | signs the PDF hash
           v
    PAdES-B signature embedded in the PDF.

Verification uses only the root CA loaded from SSM as its trust anchor;
we do NOT consult the OS trust bundle, so the mocked chain is validated
in isolation from real-world CAs. Adobe Reader shows a green check only
if the user manually imports our root cert.

Constants live at the top; everything else is documented per function.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional

import boto3
from asn1crypto import keys as a_keys
from asn1crypto import pem as a_pem
from asn1crypto import x509 as a_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import PdfSigner, SimpleSigner
from pyhanko.sign.fields import SigFieldSpec, append_signature_field
from pyhanko.sign.signers import PdfSignatureMetadata
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.registry import SimpleCertificateStore

from libs.core.logger import Logger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KEY_SIZE = 2048
HASH_ALGORITHM = "sha256"
SIG_FIELD_NAME = "CDTsSignature1"

# Serial format: 32 hex chars (128 bits of entropy). Fits VARCHAR(64) in the
# `signatures` table without truncation.
_SERIAL_ENTROPY_BYTES = 16

# Default box size when caller does not provide width_pct / height_pct. Sized
# for a Letter/A4 page; caller can override for other formats.
_DEFAULT_SIG_WIDTH_PCT = 25.0
_DEFAULT_SIG_HEIGHT_PCT = 6.0


# ---------------------------------------------------------------------------
# Root CA loading (SSM, lazy, cached per warm Lambda container)
# ---------------------------------------------------------------------------
_root_ca_cache: Optional[tuple[bytes, bytes]] = None


def _ssm_param_names(stage: str) -> tuple[str, str]:
    """Returns (cert_param_name, private_key_param_name) for this stage."""
    return (
        f"/cdts/{stage}/mock-ca/root/cert-pem",
        f"/cdts/{stage}/mock-ca/root/private-key-pem",
    )


def _load_root_ca() -> tuple[bytes, bytes]:
    """Reads the root CA cert + private key from SSM.

    Returns (cert_pem_bytes, private_key_pem_bytes). Cached at module
    scope so a warm Lambda re-uses it. On cold start this makes exactly
    two SSM calls.

    Raises RuntimeError if either SSM parameter is missing; the operator
    must bootstrap the root CA with `openssl` as documented in
    docs/signatures-v2.md before deploying signatures v2.
    """
    global _root_ca_cache
    if _root_ca_cache is not None:
        return _root_ca_cache

    stage = os.environ.get("STAGE")
    if not stage:
        raise RuntimeError("STAGE env var is not set; cannot resolve SSM path")
    cert_param, key_param = _ssm_param_names(stage)

    ssm = boto3.client("ssm")
    try:
        cert_resp = ssm.get_parameter(Name=cert_param, WithDecryption=True)
        key_resp = ssm.get_parameter(Name=key_param, WithDecryption=True)
    except Exception as e:
        raise RuntimeError(
            f"Mock CA root not found in SSM ({cert_param} + {key_param}). "
            f"Bootstrap it with the openssl commands in docs/signatures-v2.md. "
            f"Underlying error: {e}"
        ) from e

    cert_pem = cert_resp["Parameter"]["Value"].encode("utf-8")
    key_pem = key_resp["Parameter"]["Value"].encode("utf-8")
    _root_ca_cache = (cert_pem, key_pem)
    Logger.log("INFO", f"mock_ca root loaded from SSM ({cert_param})")
    return _root_ca_cache


def _reset_root_ca_cache_for_tests() -> None:
    """Test hook: force the next `_load_root_ca` call to re-fetch."""
    global _root_ca_cache
    _root_ca_cache = None


# ---------------------------------------------------------------------------
# PEM/DER conversion helpers
# ---------------------------------------------------------------------------
def _pem_to_der(pem_bytes: bytes) -> bytes:
    """Strips PEM armor and returns DER. Accepts CERTIFICATE or PRIVATE KEY."""
    _, _, der = a_pem.unarmor(pem_bytes)
    return der


def _to_asn1_cert(pem_or_der: bytes) -> a_x509.Certificate:
    der = _pem_to_der(pem_or_der) if a_pem.detect(pem_or_der) else pem_or_der
    return a_x509.Certificate.load(der)


def _to_asn1_key(pem_or_der: bytes) -> a_keys.PrivateKeyInfo:
    der = _pem_to_der(pem_or_der) if a_pem.detect(pem_or_der) else pem_or_der
    return a_keys.PrivateKeyInfo.load(der)


def _cryptography_private_key_from_pem(pem_bytes: bytes):
    return serialization.load_pem_private_key(pem_bytes, password=None)


def _cryptography_cert_from_pem(pem_bytes: bytes) -> x509.Certificate:
    return x509.load_pem_x509_certificate(pem_bytes)


# ---------------------------------------------------------------------------
# 1) Issue an ephemeral transaction certificate
# ---------------------------------------------------------------------------
def issue_transaction_cert(
    sign_id: str,
    signer_email: str,
    signer_name: Optional[str] = None,
    valid_hours: int = 1,
) -> tuple[bytes, bytes, str]:
    """Generates an RSA-2048 keypair and issues a leaf X.509 certificate
    signed by the root CA in SSM.

    Returns (cert_pem, private_key_pem, serial_hex).

    Design decisions:
    * The private key is returned as PEM bytes so the caller can pass it
      into `sign_pdf_pades_b` in the same invocation and then discard.
      It is never written to any persistent store.
    * `serial_hex` is 32 hex chars (128 bits of entropy). Persisted in
      `signatures.cert_serial` for later lookups.
    * Subject uses the signer's email + name (falls back to email if the
      name is empty); OU=sign_id ties the cert to the transaction for
      audit.
    * Validity is intentionally short so a leaked leaf cert stops being
      useful within an hour. The signature remains verifiable long after
      because PAdES stamps the signing time inside the signed attrs.
    """
    if not signer_email:
        raise ValueError("signer_email is required")

    root_cert_pem, root_key_pem = _load_root_ca()
    root_cert = _cryptography_cert_from_pem(root_cert_pem)
    root_key = _cryptography_private_key_from_pem(root_key_pem)

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)

    display_name = (signer_name or signer_email).strip()
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, display_name[:64]),
            x509.NameAttribute(NameOID.EMAIL_ADDRESS, signer_email.strip().lower()),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, sign_id[:64]),
        ]
    )
    now = datetime.now(timezone.utc)
    serial_int = int.from_bytes(secrets.token_bytes(_SERIAL_ENTROPY_BYTES), "big")

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(root_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(serial_int)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(hours=valid_hours))
        # Leaf, not a CA. Required by PAdES verifiers that enforce it.
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        # Digital signature + content commitment (non-repudiation): the exact
        # KUs a PAdES signer cert should carry.
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        # SubjectAltName with the email is what Adobe/pyhanko use to bind
        # the certificate to an identity for display.
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.RFC822Name(signer_email.strip().lower())]
            ),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = leaf_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    serial_hex = format(serial_int, "032x")

    Logger.log(
        "INFO",
        f"mock_ca issued cert serial={serial_hex} for sign_id={sign_id} "
        f"email={signer_email} valid_hours={valid_hours}",
    )
    return cert_pem, key_pem, serial_hex


# ---------------------------------------------------------------------------
# 2) Sign a PDF (PAdES-B baseline)
# ---------------------------------------------------------------------------
def _resolve_signature_box(
    pdf_bytes: bytes, signature_location: dict
) -> tuple[int, tuple[float, float, float, float]]:
    """Translates the caller's `{page, x_pct, y_pct, [width_pct, height_pct]}`
    (percentages from the TOP-LEFT of the page, matching the frontend UI)
    into pyhanko's `(on_page_zero_indexed, (llx, lly, urx, ury))` box
    with coordinates in PDF points measured from the BOTTOM-LEFT (PDF
    native origin).
    """
    page = int(signature_location["page"])
    x_pct = float(signature_location["x_pct"])
    y_pct = float(signature_location["y_pct"])
    width_pct = float(signature_location.get("width_pct", _DEFAULT_SIG_WIDTH_PCT))
    height_pct = float(signature_location.get("height_pct", _DEFAULT_SIG_HEIGHT_PCT))

    if not (0 <= x_pct <= 100 and 0 <= y_pct <= 100):
        raise ValueError("x_pct/y_pct must be in [0, 100]")

    # Read the page size (in points) to convert percentages to absolute box.
    # We use pypdf here (lightweight, already a signatures dep) rather than
    # opening a second pyhanko reader.
    from pypdf import PdfReader

    r = PdfReader(BytesIO(pdf_bytes))
    if page < 1 or page > len(r.pages):
        raise ValueError(
            f"page {page} out of range (PDF has {len(r.pages)} pages)"
        )
    mb = r.pages[page - 1].mediabox
    page_w = float(mb.width)
    page_h = float(mb.height)

    box_w = page_w * (width_pct / 100.0)
    box_h = page_h * (height_pct / 100.0)
    # y_pct is measured from the TOP; flip to bottom-anchored PDF coords.
    llx = page_w * (x_pct / 100.0)
    ury = page_h - page_h * (y_pct / 100.0)
    lly = ury - box_h
    urx = llx + box_w

    return page - 1, (llx, lly, urx, ury)


def _build_signer(cert_pem: bytes, private_key_pem: bytes) -> SimpleSigner:
    """Wraps a leaf cert + private key + root CA (loaded from SSM) into a
    pyhanko SimpleSigner. Embeds the root in `cert_registry` so verifiers
    that don't have it pre-loaded can still reconstruct the chain from the
    embedded PKCS#7."""
    root_cert_pem, _ = _load_root_ca()

    registry = SimpleCertificateStore()
    registry.register(_to_asn1_cert(root_cert_pem))

    return SimpleSigner(
        signing_cert=_to_asn1_cert(cert_pem),
        signing_key=_to_asn1_key(private_key_pem),
        cert_registry=registry,
    )


def sign_pdf_pades_b(
    pdf_bytes: bytes,
    cert_pem: bytes,
    private_key_pem: bytes,
    signature_location: dict,
    *,
    reason: str = "Digital signature via CDTs Mock CA",
    location: Optional[str] = None,
) -> bytes:
    """Signs `pdf_bytes` with a visible PAdES-B baseline signature.

    Arguments:
        pdf_bytes: the PDF to sign, as bytes.
        cert_pem, private_key_pem: from `issue_transaction_cert`.
        signature_location: `{page, x_pct, y_pct, [width_pct, height_pct]}`.
            Percentages are measured from the TOP-LEFT of the page (UI
            convention). Coordinates are converted to PDF-native
            bottom-left for pyhanko.
        reason: PDF signature reason field. Free text.
        location: PDF signature location field. Optional.

    Returns the signed PDF as bytes. Not idempotent: signing twice adds
    two signature fields.
    """
    if not pdf_bytes:
        raise ValueError("pdf_bytes is required")

    page_zero_indexed, box = _resolve_signature_box(pdf_bytes, signature_location)
    signer = _build_signer(cert_pem, private_key_pem)

    w = IncrementalPdfFileWriter(BytesIO(pdf_bytes))
    append_signature_field(
        w,
        sig_field_spec=SigFieldSpec(
            sig_field_name=SIG_FIELD_NAME,
            on_page=page_zero_indexed,
            box=box,
        ),
    )
    pdf_signer = PdfSigner(
        signature_meta=PdfSignatureMetadata(
            field_name=SIG_FIELD_NAME,
            md_algorithm=HASH_ALGORITHM,
            reason=reason,
            location=location,
        ),
        signer=signer,
    )
    out = BytesIO()
    pdf_signer.sign_pdf(w, output=out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# 3) Verify a signed PDF
# ---------------------------------------------------------------------------
def verify_pades_pdf(pdf_bytes: bytes) -> dict:
    """Verifies the embedded PAdES signature against the root CA in SSM.

    Returns a dict shaped like:

        {
            "valid": bool,                # overall pass/fail
            "document_integrity": bool,   # bytes intact vs signed hash
            "signature_valid": bool,      # RSA signature verifies vs cert
            "certificate_valid": bool,    # chain reaches root CA
            "signer_email": str | None,
            "signer_name": str | None,
            "cert_serial": str | None,    # 32-hex, matches DB column
            "signed_at": str | None,      # ISO8601 UTC
            "reason": str | None,         # non-empty if not valid
        }

    Does not consult the OS trust bundle. Only the mocked root CA (from
    SSM) is a trust anchor.
    """
    result = {
        "valid": False,
        "document_integrity": False,
        "signature_valid": False,
        "certificate_valid": False,
        "signer_email": None,
        "signer_name": None,
        "cert_serial": None,
        "signed_at": None,
        "reason": None,
    }

    try:
        reader = PdfFileReader(BytesIO(pdf_bytes))
        embedded = list(reader.embedded_signatures)
    except Exception as e:
        result["reason"] = f"could_not_parse_pdf: {e}"
        return result

    if not embedded:
        result["reason"] = "no_signatures_present"
        return result

    # We only sign once per PDF (SIG_FIELD_NAME is fixed). Pick the first;
    # if the PDF has more, the caller can extend this to iterate.
    sig = embedded[0]

    try:
        root_cert_pem, _ = _load_root_ca()
        vc = ValidationContext(trust_roots=[_to_asn1_cert(root_cert_pem)])
        status = validate_pdf_signature(sig, vc)
    except Exception as e:
        result["reason"] = f"verification_error: {e}"
        return result

    result["document_integrity"] = bool(status.intact)
    result["signature_valid"] = bool(status.valid)
    result["certificate_valid"] = bool(status.trusted)
    result["valid"] = result["document_integrity"] and result["signature_valid"] and result["certificate_valid"]

    signing_cert = status.signing_cert
    if signing_cert is not None:
        # Serial is stored on the DB as 32-hex; asn1crypto gives an int.
        serial_int = int(signing_cert.serial_number)
        result["cert_serial"] = format(serial_int, "032x")

        # Pull email + common name off the subject.
        subject = signing_cert.subject.native or {}
        result["signer_email"] = (
            subject.get("email_address") if isinstance(subject, dict) else None
        )
        result["signer_name"] = (
            subject.get("common_name") if isinstance(subject, dict) else None
        )

    # signer_reported_dt is the M attribute inside the PDF signature dictionary,
    # which is the SIGNER-CLAIMED signing time. It is not trustable by itself
    # (only a TSA-anchored timestamp is), but it is what the audit trail wants.
    signed_at = getattr(sig, "self_reported_timestamp", None) or getattr(
        sig, "signer_reported_dt", None
    )
    if signed_at is not None:
        try:
            result["signed_at"] = signed_at.isoformat()
        except Exception:
            result["signed_at"] = str(signed_at)

    if not result["valid"] and result["reason"] is None:
        parts = []
        if not result["document_integrity"]:
            parts.append("document_tampered")
        if not result["signature_valid"]:
            parts.append("signature_invalid")
        if not result["certificate_valid"]:
            parts.append("certificate_untrusted")
        result["reason"] = ",".join(parts) or "unknown"

    return result
