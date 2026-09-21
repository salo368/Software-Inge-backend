"""Unit tests for `services/signatures/utils/evidence_package.py`.

Cross-cutting because the module is block-local to signatures. Uses the
same sys.path escape hatch as `test_mock_ca.py` and `test_stamp.py`.

The tests here treat the package as a pure data assembler: given a
Signatures-shaped mock, verify the resulting JSON is self-describing
and carries every field an auditor will need.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[4]
_SIG_UTILS = _BACKEND / "services" / "signatures" / "utils"
sys.path.insert(0, str(_SIG_UTILS))

for _n in list(sys.modules):
    if _n == "utils" or _n.startswith("utils."):
        sys.modules.pop(_n, None)

import evidence_package  # noqa: E402


def _row(**overrides):
    """Builds a Signatures-shaped SimpleNamespace with sane defaults."""
    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    defaults = {
        "sign_id": "abc",
        "service_caller": "processes",
        "signer_email": "signer@example.com",
        "signer_name": "Signer",
        "masked_email": "si***@example.com",
        "signature_location": {"page": 1, "x_pct": 10, "y_pct": 20},
        "hash_original": "a" * 64,
        "hash_signed": "b" * 64,
        "cert_serial": "c" * 32,
        "signed_at": now,
        "consent_given_at": now,
        "consent_terms_version": "v1.0",
        "created_at": now,
        "expires_at": now,
        "uploads_state": {
            "id_front": {"uploaded": True, "key": "k1"},
            "id_back": {"uploaded": True, "key": "k2"},
            "face": {"uploaded": True, "key": "k3"},
            "signature": {"uploaded": True, "key": "k4"},
        },
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestSchema:
    def test_all_top_level_sections_present(self):
        pkg = evidence_package.build_evidence_package(
            signature=_row(),
            signed_pdf_key="transactions/abc/signed.pdf",
            original_pdf_key="transactions/abc/original.pdf",
            cert_pem="cert_pem_body",
        )
        for section in (
            "schema_version",
            "generated_at",
            "sign_id",
            "service_caller",
            "signer",
            "document",
            "evidences",
            "consent",
            "otp",
            "signature",
            "timing",
        ):
            assert section in pkg

    def test_document_embeds_hashes_and_keys(self):
        pkg = evidence_package.build_evidence_package(
            signature=_row(),
            signed_pdf_key="transactions/abc/signed.pdf",
            original_pdf_key="transactions/abc/original.pdf",
            cert_pem="cert",
        )
        doc = pkg["document"]
        assert doc["signed_key"] == "transactions/abc/signed.pdf"
        assert doc["original_key"] == "transactions/abc/original.pdf"
        assert doc["hash_original"] == "a" * 64
        assert doc["hash_signed"] == "b" * 64
        assert doc["signature_location"]["page"] == 1

    def test_signature_section_carries_cert_material(self):
        pkg = evidence_package.build_evidence_package(
            signature=_row(),
            signed_pdf_key="k1",
            original_pdf_key="k0",
            cert_pem="PEMBODY",
        )
        s = pkg["signature"]
        assert s["algorithm"] == "PAdES-B baseline"
        assert s["hash_algorithm"] == "sha256"
        assert s["cert_serial"] == "c" * 32
        assert s["cert_pem"] == "PEMBODY"
        assert s["signed_at"] is not None


class TestSerialization:
    def test_output_json_serialisable(self):
        pkg = evidence_package.build_evidence_package(
            signature=_row(),
            signed_pdf_key="k1",
            original_pdf_key="k0",
            cert_pem="pem",
        )
        # Must round-trip through json without a `default=` fallback --
        # any datetime should already be ISO-string.
        blob = json.dumps(pkg)
        again = json.loads(blob)
        assert again["sign_id"] == "abc"

    def test_naive_datetimes_are_treated_as_utc(self):
        """Postgres often returns naive datetimes. The package must
        still emit ISO strings with a UTC offset so auditors can parse
        them unambiguously."""
        naive = datetime(2026, 9, 20, 12, 0)  # no tzinfo
        pkg = evidence_package.build_evidence_package(
            signature=_row(consent_given_at=naive, signed_at=naive),
            signed_pdf_key="k",
            original_pdf_key="k0",
            cert_pem="pem",
        )
        assert pkg["consent"]["given_at"].endswith("+00:00")
        assert pkg["signature"]["signed_at"].endswith("+00:00")


class TestOptionalFields:
    def test_missing_signer_name_serialises_as_null(self):
        pkg = evidence_package.build_evidence_package(
            signature=_row(signer_name=None),
            signed_pdf_key="k",
            original_pdf_key="k0",
            cert_pem="pem",
        )
        assert pkg["signer"]["name"] is None

    def test_missing_consent_serialises_as_null(self):
        pkg = evidence_package.build_evidence_package(
            signature=_row(consent_given_at=None, consent_terms_version=None),
            signed_pdf_key="k",
            original_pdf_key="k0",
            cert_pem="pem",
        )
        assert pkg["consent"]["given_at"] is None
        assert pkg["consent"]["terms_version"] is None
