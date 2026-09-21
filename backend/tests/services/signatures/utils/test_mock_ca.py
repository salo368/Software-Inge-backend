"""Unit tests for `services/signatures/utils/mock_ca.py`.

Cross-cutting because the module is block-local to signatures but we
want its tests to live outside the handler-colocation pattern (there is
no `handler.py` here). Follows the same sys.path-adjustment approach as
`tests/test_migrations_parser.py`.

The root CA is generated in memory per-test and injected via
monkeypatch on `_load_root_ca`; no test hits real SSM.

Roundtrip coverage:
    issue -> sign -> verify (happy path)
    issue -> sign -> tamper bytes -> verify shows integrity=False
    issue -> sign -> verify with WRONG root -> trusted=False
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make `services/signatures/utils/mock_ca.py` importable without going
# through the `utils.<name>` namespace-package indirection that the
# handler-colocated tests rely on. We import `mock_ca` bare here.
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parents[4]
_SIG_UTILS = _BACKEND / "services" / "signatures" / "utils"
sys.path.insert(0, str(_SIG_UTILS))

# Purge any prior `utils` binding another test's `load_handler` might have
# left in sys.modules; otherwise Python could resolve `mock_ca` against
# a stale namespace if we ever add `from utils import mock_ca` here.
for _n in list(sys.modules):
    if _n == "utils" or _n.startswith("utils."):
        sys.modules.pop(_n, None)

import mock_ca  # noqa: E402  -- explicit sys.path setup above


# ---------------------------------------------------------------------------
# In-memory root CA (deterministic per-session generation for speed).
# ---------------------------------------------------------------------------
def _generate_in_memory_root_ca(cn: str = "TEST Root CA") -> tuple[bytes, bytes]:
    """Returns (root_cert_pem, root_key_pem)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )


# Generated ONCE per test session (RSA-2048 gen takes ~200ms; we don't
# want that per test).
_ROOT_CERT_PEM, _ROOT_KEY_PEM = _generate_in_memory_root_ca()


def _minimal_pdf() -> bytes:
    """~1.4KB single-page PDF, sufficient to hold a signature field."""
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "Test document")
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _inject_in_memory_root_ca(monkeypatch):
    """Every test in this module gets its `mock_ca._load_root_ca` swapped
    for a function that returns the in-memory-generated root. Cache is
    reset so each test starts from a clean state."""
    mock_ca._reset_root_ca_cache_for_tests()
    monkeypatch.setattr(
        mock_ca, "_load_root_ca", lambda: (_ROOT_CERT_PEM, _ROOT_KEY_PEM)
    )
    yield
    mock_ca._reset_root_ca_cache_for_tests()


# ---------------------------------------------------------------------------
# _load_root_ca / cache
# ---------------------------------------------------------------------------
class TestLoadRootCACache:
    def test_ssm_names_include_stage(self, monkeypatch):
        cert_p, key_p = mock_ca._ssm_param_names("pro")
        assert cert_p == "/cdts/pro/mock-ca/root/cert-pem"
        assert key_p == "/cdts/pro/mock-ca/root/private-key-pem"
        cert_p, key_p = mock_ca._ssm_param_names("dev")
        assert cert_p == "/cdts/dev/mock-ca/root/cert-pem"

    def test_load_caches_and_only_fetches_once(self, monkeypatch):
        """Confirm the cache actually skips SSM on the second call.

        We temporarily undo the autouse monkeypatch by patching the SSM
        client, then call `_load_root_ca` twice and count SSM invocations.
        """
        monkeypatch.setenv("STAGE", "test")
        # Undo the autouse monkeypatch by re-attaching the original.
        # (monkeypatch's setattr in the autouse fixture is scoped per test,
        # so we need to reach the ACTUAL implementation here.)
        # Simpler: use the real function via mock_ca.__dict__ before autouse.
        import importlib

        importlib.reload(mock_ca)  # re-load fresh, drops the monkeypatch
        mock_ca._reset_root_ca_cache_for_tests()

        calls = {"count": 0}

        def _fake_ssm_client():
            calls["count"] += 1
            from unittest.mock import MagicMock

            fake = MagicMock()
            fake.get_parameter.return_value = {
                "Parameter": {"Value": _ROOT_CERT_PEM.decode("ascii")}
            }
            return fake

        # boto3.client is called twice inside _load_root_ca? Actually it is
        # called ONCE, and get_parameter is called TWICE. We count boto3.client.
        monkeypatch.setattr(mock_ca, "boto3", type("B", (), {"client": staticmethod(lambda *a, **k: _fake_ssm_client())}))

        # First call: fetches from SSM.
        c1, _ = mock_ca._load_root_ca()
        assert c1 == _ROOT_CERT_PEM
        # Second call: served from cache, no new SSM client.
        c2, _ = mock_ca._load_root_ca()
        assert c2 is c1  # same tuple instance
        assert calls["count"] == 1  # only one boto3.client() call happened

    def test_load_raises_when_stage_missing(self, monkeypatch):
        monkeypatch.delenv("STAGE", raising=False)
        # Undo the autouse monkeypatch so we hit the real function.
        import importlib

        importlib.reload(mock_ca)
        mock_ca._reset_root_ca_cache_for_tests()

        with pytest.raises(RuntimeError, match="STAGE env var"):
            mock_ca._load_root_ca()


# ---------------------------------------------------------------------------
# issue_transaction_cert
# ---------------------------------------------------------------------------
class TestIssueTransactionCert:
    def test_returns_pem_cert_key_and_hex_serial(self):
        cert_pem, key_pem, serial = mock_ca.issue_transaction_cert(
            sign_id="sign_abc123",
            signer_email="alice@example.com",
            signer_name="Alice Test",
        )
        assert cert_pem.startswith(b"-----BEGIN CERTIFICATE-----")
        assert key_pem.startswith(b"-----BEGIN PRIVATE KEY-----")
        assert len(serial) == 32
        int(serial, 16)  # valid hex

    def test_cert_is_signed_by_root_and_has_right_subject(self):
        cert_pem, _, _ = mock_ca.issue_transaction_cert(
            sign_id="sign_xyz",
            signer_email="Bob@Example.COM",
            signer_name="Bob Test",
        )
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import padding

        leaf = x509.load_pem_x509_certificate(cert_pem)
        root = x509.load_pem_x509_certificate(_ROOT_CERT_PEM)

        # Issuer of leaf == subject of root.
        assert leaf.issuer == root.subject

        # Cryptographic verification of the signature on the leaf.
        root.public_key().verify(
            leaf.signature,
            leaf.tbs_certificate_bytes,
            padding.PKCS1v15(),
            leaf.signature_hash_algorithm,
        )

        # Subject fields: CN=name, emailAddress lowercased, OU=sign_id.
        cns = [a.value for a in leaf.subject if a.oid.dotted_string == "2.5.4.3"]
        emails = [a.value for a in leaf.subject if a.oid.dotted_string == "1.2.840.113549.1.9.1"]
        ous = [a.value for a in leaf.subject if a.oid.dotted_string == "2.5.4.11"]
        assert cns == ["Bob Test"]
        assert emails == ["bob@example.com"]  # lowercased
        assert ous == ["sign_xyz"]

    def test_validity_is_one_hour_by_default(self):
        cert_pem, _, _ = mock_ca.issue_transaction_cert(
            sign_id="s", signer_email="c@d.co"
        )
        from cryptography import x509

        leaf = x509.load_pem_x509_certificate(cert_pem)
        # Use the timezone-aware _utc accessors when available (newer cryptography).
        try:
            not_before = leaf.not_valid_before_utc
            not_after = leaf.not_valid_after_utc
        except AttributeError:  # pragma: no cover -- older cryptography
            not_before = leaf.not_valid_before.replace(tzinfo=timezone.utc)
            not_after = leaf.not_valid_after.replace(tzinfo=timezone.utc)
        assert timedelta(minutes=59) <= (not_after - not_before) <= timedelta(minutes=61)

    def test_falls_back_to_email_when_name_is_empty(self):
        cert_pem, _, _ = mock_ca.issue_transaction_cert(
            sign_id="s", signer_email="only@email.co", signer_name=None
        )
        from cryptography import x509

        leaf = x509.load_pem_x509_certificate(cert_pem)
        cns = [a.value for a in leaf.subject if a.oid.dotted_string == "2.5.4.3"]
        assert cns == ["only@email.co"]

    def test_serial_is_unique_across_issuances(self):
        seen = set()
        for _ in range(10):
            _, _, s = mock_ca.issue_transaction_cert(
                sign_id="s", signer_email="a@b.co"
            )
            assert s not in seen
            seen.add(s)

    def test_rejects_empty_email(self):
        with pytest.raises(ValueError):
            mock_ca.issue_transaction_cert(sign_id="s", signer_email="")


# ---------------------------------------------------------------------------
# sign_pdf_pades_b + verify_pades_pdf roundtrip
# ---------------------------------------------------------------------------
class TestSignAndVerifyRoundtrip:
    def test_happy_roundtrip_full_valid(self):
        cert_pem, key_pem, serial = mock_ca.issue_transaction_cert(
            sign_id="sign_rt1",
            signer_email="roundtrip@example.com",
            signer_name="Round Trip",
        )
        pdf = _minimal_pdf()

        signed = mock_ca.sign_pdf_pades_b(
            pdf, cert_pem, key_pem,
            signature_location={"page": 1, "x_pct": 10, "y_pct": 80},
        )
        assert signed.startswith(b"%PDF-")
        assert len(signed) > len(pdf)  # signature adds bytes

        result = mock_ca.verify_pades_pdf(signed)
        assert result["valid"] is True
        assert result["document_integrity"] is True
        assert result["signature_valid"] is True
        assert result["certificate_valid"] is True
        assert result["signer_email"] == "roundtrip@example.com"
        assert result["signer_name"] == "Round Trip"
        assert result["cert_serial"] == serial

    def test_tampered_bytes_break_integrity(self):
        cert_pem, key_pem, _ = mock_ca.issue_transaction_cert(
            sign_id="sign_tamper",
            signer_email="tamper@example.com",
        )
        pdf = _minimal_pdf()
        signed = mock_ca.sign_pdf_pades_b(
            pdf, cert_pem, key_pem,
            signature_location={"page": 1, "x_pct": 10, "y_pct": 80},
        )

        # Flip a byte inside the original content region. The signed PDF
        # layout is roughly:
        #   [original PDF content ~1.4KB] [signature dict + hash placeholder]
        # so a byte at offset 200 is safely inside the original range which
        # /ByteRange covers -> flipping it must break integrity.
        tampered = bytearray(signed)
        original_len_estimate = 300  # well within the original PDF header/body
        tampered[original_len_estimate] ^= 0xFF  # flip all bits
        tampered = bytes(tampered)

        result = mock_ca.verify_pades_pdf(tampered)
        assert result["valid"] is False
        assert result["document_integrity"] is False
        assert "document_tampered" in (result["reason"] or "")

    def test_wrong_root_makes_cert_untrusted(self, monkeypatch):
        """Sign with our real root, but verify with a DIFFERENT root."""
        cert_pem, key_pem, _ = mock_ca.issue_transaction_cert(
            sign_id="sign_wrongroot",
            signer_email="wrongroot@example.com",
        )
        pdf = _minimal_pdf()
        signed = mock_ca.sign_pdf_pades_b(
            pdf, cert_pem, key_pem,
            signature_location={"page": 1, "x_pct": 10, "y_pct": 80},
        )

        # Swap the CA used by verify (autouse fixture is patched at fn scope,
        # so this reassignment only lasts for this test).
        other_root_pem, other_root_key = _generate_in_memory_root_ca(
            cn="Different Root"
        )
        monkeypatch.setattr(
            mock_ca, "_load_root_ca", lambda: (other_root_pem, other_root_key)
        )

        result = mock_ca.verify_pades_pdf(signed)
        assert result["valid"] is False
        assert result["certificate_valid"] is False
        # integrity + signature-vs-key still pass (the bytes and RSA math
        # are fine), only the chain is broken.
        assert result["document_integrity"] is True
        assert result["signature_valid"] is True

    def test_no_signatures_reason(self):
        """A vanilla PDF returns a clean 'no signatures' reason."""
        result = mock_ca.verify_pades_pdf(_minimal_pdf())
        assert result["valid"] is False
        assert result["reason"] == "no_signatures_present"

    def test_garbage_bytes_do_not_raise(self):
        result = mock_ca.verify_pades_pdf(b"not-a-pdf")
        assert result["valid"] is False
        assert (result["reason"] or "").startswith("could_not_parse_pdf")


# ---------------------------------------------------------------------------
# signature location translation
# ---------------------------------------------------------------------------
class TestSignatureBoxResolution:
    def test_percentages_flip_y_axis(self):
        pdf = _minimal_pdf()
        # y_pct=0 (top of page in UI) should produce a box whose upper edge
        # is near the top of the page (high PDF y).
        page_idx, (llx, lly, urx, ury) = mock_ca._resolve_signature_box(
            pdf,
            {"page": 1, "x_pct": 0, "y_pct": 0, "width_pct": 10, "height_pct": 5},
        )
        assert page_idx == 0
        # reportlab defaults to A4: 595.276 x 841.890 points.
        page_w, page_h = 595.2755905511812, 841.8897637795275
        # x_pct=0 -> llx == 0
        assert llx == pytest.approx(0)
        # y_pct=0 from top -> ury == page_height
        assert ury == pytest.approx(page_h)
        # box_h = 5% of page_h
        assert lly == pytest.approx(page_h - page_h * 0.05)
        # box_w = 10% of page_w
        assert urx == pytest.approx(page_w * 0.10)

    def test_bad_page_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            mock_ca._resolve_signature_box(
                _minimal_pdf(),
                {"page": 99, "x_pct": 10, "y_pct": 80},
            )

    def test_bad_percentages_raise(self):
        with pytest.raises(ValueError, match=r"x_pct/y_pct"):
            mock_ca._resolve_signature_box(
                _minimal_pdf(),
                {"page": 1, "x_pct": 150, "y_pct": 80},
            )
