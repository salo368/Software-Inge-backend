"""Mock Certification Authority for the signatures service.

Ported from services/signatures/_legacy/utils/mock_ca.py, trimmed to
just the two operations `sign_doc` needs (issuing a transaction cert
and PAdES-signing a PDF with it). `verify_pades_pdf` is not ported --
there's no /verify endpoint yet in this refactor.

Trust model (mocked, same root as the legacy service):

    /cdts/{stage}/mock-ca/root/cert-pem        <-- SSM SecureString (KMS)
    /cdts/{stage}/mock-ca/root/private-key-pem <-- SSM SecureString (KMS)

    root CA cert + private key (bootstrapped manually per stage)
           |
           | signs (this is the ONLY thing the root key ever touches --
           |        it certifies a new leaf, never a document directly)
           v
    ephemeral leaf cert (per signature, 1h validity); its private key
    lives only in the invoking Lambda's memory for the call's duration
           |
           | signs the PDF hash
           v
    PAdES-B signature embedded in the PDF.
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
from pyhanko.sign import PdfSigner, SimpleSigner
from pyhanko.sign.fields import SigFieldSpec, append_signature_field
from pyhanko.sign.signers import PdfSignatureMetadata
from pyhanko_certvalidator.registry import SimpleCertificateStore

from libs.core.logger import Logger

KEY_SIZE = 2048
HASH_ALGORITHM = "sha256"
SIG_FIELD_NAME = "CDTsSignature1"

# 32 hex chars (128 bits of entropy).
_SERIAL_ENTROPY_BYTES = 16

_root_ca_cache: Optional[tuple[bytes, bytes]] = None


def _ssm_param_names(stage: str) -> tuple[str, str]:
    return (
        f"/cdts/{stage}/mock-ca/root/cert-pem",
        f"/cdts/{stage}/mock-ca/root/private-key-pem",
    )


def _load_root_ca() -> tuple[bytes, bytes]:
    """Reads the root CA cert + private key from SSM, cached per warm
    container. Raises RuntimeError if the root isn't bootstrapped yet."""
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
            f"Underlying error: {e}"
        ) from e

    cert_pem = cert_resp["Parameter"]["Value"].encode("utf-8")
    key_pem = key_resp["Parameter"]["Value"].encode("utf-8")
    _root_ca_cache = (cert_pem, key_pem)
    Logger.log("INFO", f"signature_ca root loaded from SSM ({cert_param})")
    return _root_ca_cache


def _pem_to_der(pem_bytes: bytes) -> bytes:
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
    signature_id: str,
    signer_email: str,
    signer_name: Optional[str] = None,
    valid_hours: int = 1,
) -> tuple[bytes, bytes, str]:
    """Generates an RSA-2048 keypair and issues a leaf X.509 certificate
    signed by the root CA in SSM. Returns (cert_pem, private_key_pem,
    serial_hex). The private key is never persisted anywhere -- the
    caller signs the PDF with it in the same invocation and discards it."""
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
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, str(signature_id)[:64]),
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
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
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
        .add_extension(
            x509.SubjectAlternativeName([x509.RFC822Name(signer_email.strip().lower())]),
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
        f"signature_ca issued cert serial={serial_hex} for signature_id={signature_id} "
        f"valid_hours={valid_hours}",
    )
    return cert_pem, key_pem, serial_hex


# ---------------------------------------------------------------------------
# 2) Sign a PDF (PAdES-B baseline)
# ---------------------------------------------------------------------------
def _build_signer(cert_pem: bytes, private_key_pem: bytes) -> SimpleSigner:
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
    *,
    reason: str = "Digital signature via CDTs Mock CA",
    location: Optional[str] = None,
) -> bytes:
    """Signs `pdf_bytes` with a PAdES-B baseline signature (invisible
    widget -- the signer's drawn autograph, already stamped onto the
    page by `signature_stamp`, is the visual affordance; PAdES-B is
    fully valid without a widget, and readers still show the panel)."""
    if not pdf_bytes:
        raise ValueError("pdf_bytes is required")

    signer = _build_signer(cert_pem, private_key_pem)
    w = IncrementalPdfFileWriter(BytesIO(pdf_bytes))

    spec = SigFieldSpec(sig_field_name=SIG_FIELD_NAME)
    append_signature_field(w, sig_field_spec=spec)
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
