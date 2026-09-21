"""Unit tests for signatures/sign.

The `sign` handler is an async worker (no HTTP event), so tests here
exercise `handler(payload, None)` directly. All external dependencies
are stubbed:

    * Signatures.get_by_sign_id      -> returns a MagicMock row
    * boto3.client('s3')             -> MagicMock with get_object/put_object
    * mock_ca.issue_transaction_cert -> MagicMock returning fake bytes
    * mock_ca.sign_pdf_pades_b       -> MagicMock returning fake bytes
    * stamp.stamp_drawing_on_pdf     -> MagicMock returning fake bytes
    * requests.post                  -> MagicMock returning a fake Response
    * db_session                     -> MagicMock (commit/rollback/close)

The tests focus on the STATE MACHINE (which row methods are called with
what) and on ERROR ISOLATION (a failure at any step marks the ceremony
failed with a stable code). Actual PDF/PAdES correctness is exercised
by test_mock_ca.py + test_stamp.py.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock


_FAKE_ORIGINAL_PDF = b"%PDF-1.7\n%fake original\n%%EOF"
_FAKE_STAMPED_PDF = b"%PDF-1.7\n%fake stamped\n%%EOF"
_FAKE_SIGNED_PDF = b"%PDF-1.7\n%fake signed\n%%EOF"
_FAKE_DRAWING_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 2000
_FAKE_CERT_PEM = b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"
_FAKE_KEY_PEM = b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n"
_FAKE_SERIAL = "0123456789abcdef0123456789abcdef"


def _fake_row(**overrides) -> MagicMock:
    original_hash = hashlib.sha256(_FAKE_ORIGINAL_PDF).hexdigest()
    defaults = {
        "sign_id": "sign_abc",
        "stage": "signing",
        "signer_email": "signer@example.com",
        "signer_name": "Signer",
        "signature_location": {
            "page": 1,
            "x_pct": 20,
            "y_pct": 30,
            "width_pct": 25,
        },
        "signature_key": "transactions/sign_abc/signature.png",
        "hash_original": original_hash,
        "hash_signed": None,
        "cert_serial": None,
        "signed_at": None,
        "callback_url": None,
        "callback_sent_at": None,
        "callback_failed_at": None,
        "callback_error": None,
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
        "expires_at": datetime(2026, 9, 21, tzinfo=timezone.utc),
        "service_caller": "processes",
        "consent_given_at": datetime(2026, 9, 20, 12, tzinfo=timezone.utc),
        "consent_terms_version": "v1.0",
        "signer_email_masked": "si***@example.com",
        "masked_email": "si***@example.com",
    }
    defaults.update(overrides)
    m = MagicMock(**defaults)
    m.uploads_state = {
        "id_front": {"uploaded": True, "key": "k1", "validated": True, "validated_at": None},
        "id_back": {"uploaded": True, "key": "k2", "validated": True, "validated_at": None},
        "face": {"uploaded": True, "key": "k3", "validated": True, "validated_at": None},
        "signature": {"uploaded": True, "key": "k4", "validated": None, "validated_at": None},
    }

    def _mark_signed(*, hash_signed, cert_serial, signed_at):
        m.hash_signed = hash_signed
        m.cert_serial = cert_serial
        m.signed_at = signed_at
        m.stage = "signed"

    def _mark_failed(error=None):
        m.stage = "failed"
        m.callback_error = error

    def _record_callback(*, sent, error=None):
        if sent:
            m.callback_sent_at = datetime.now(timezone.utc)
            m.callback_error = None
        else:
            m.callback_failed_at = datetime.now(timezone.utc)
            m.callback_error = error

    m.mark_signed = MagicMock(side_effect=_mark_signed)
    m.mark_failed = MagicMock(side_effect=_mark_failed)
    m.record_callback = MagicMock(side_effect=_record_callback)
    return m


class _FakeS3:
    """S3 client stub. `get_object` reads from `_objects`; `put_object`
    writes to `_objects` so tests can assert on what was uploaded."""

    def __init__(self):
        self._objects: dict[str, bytes] = {}

    def prime(self, key: str, body: bytes) -> None:
        self._objects[key] = body

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self._objects:
            raise KeyError(Key)
        body = MagicMock()
        body.read = MagicMock(return_value=self._objects[Key])
        return {"Body": body}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803
        self._objects[Key] = Body

    def dump(self) -> dict[str, bytes]:
        return dict(self._objects)


def _wire(
    h,
    monkeypatch,
    *,
    row,
    s3: _FakeS3 | None = None,
    issue_raises: Exception | None = None,
    stamp_raises: Exception | None = None,
    sign_raises: Exception | None = None,
    callback_resp=None,
    callback_raises: Exception | None = None,
):
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )

    s3 = s3 or _FakeS3()
    if row is not None and row.signature_key:
        s3.prime(row.signature_key, _FAKE_DRAWING_PNG)
        s3.prime(
            f"transactions/{row.sign_id}/original.pdf", _FAKE_ORIGINAL_PDF
        )
    monkeypatch.setattr(h, "_s3", MagicMock(return_value=s3))

    monkeypatch.setattr(
        h,
        "issue_transaction_cert",
        MagicMock(
            side_effect=issue_raises,
            return_value=(_FAKE_CERT_PEM, _FAKE_KEY_PEM, _FAKE_SERIAL),
        )
        if issue_raises is None
        else MagicMock(side_effect=issue_raises),
    )
    monkeypatch.setattr(
        h,
        "stamp_drawing_on_pdf",
        MagicMock(
            side_effect=stamp_raises,
            return_value=_FAKE_STAMPED_PDF,
        )
        if stamp_raises is None
        else MagicMock(side_effect=stamp_raises),
    )
    monkeypatch.setattr(
        h,
        "sign_pdf_pades_b",
        MagicMock(
            side_effect=sign_raises,
            return_value=_FAKE_SIGNED_PDF,
        )
        if sign_raises is None
        else MagicMock(side_effect=sign_raises),
    )

    # Neutralise db_session so we don't hit the real engine.
    monkeypatch.setattr(h.db_session, "commit", MagicMock())
    monkeypatch.setattr(h.db_session, "rollback", MagicMock())
    monkeypatch.setattr(h.db_session, "close", MagicMock())

    if callback_raises is not None:
        fake_requests = MagicMock()
        fake_requests.post = MagicMock(side_effect=callback_raises)
        fake_requests.RequestException = h.requests.RequestException
        monkeypatch.setattr(h, "requests", fake_requests)
    elif callback_resp is not None:
        fake_resp = MagicMock(status_code=callback_resp)
        fake_requests = MagicMock()
        fake_requests.post = MagicMock(return_value=fake_resp)
        fake_requests.RequestException = h.requests.RequestException
        monkeypatch.setattr(h, "requests", fake_requests)

    return s3


# ---------------------------------------------------------------------------
# Payload / lookup
# ---------------------------------------------------------------------------
class TestPayload:
    def test_missing_sign_id_returns_error(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        assert h.handler({}, None) == {"ok": False, "error": "missing_sign_id"}

    def test_unknown_sign_id_returns_error(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None)
        assert h.handler({"sign_id": "nope"}, None) == {
            "ok": False,
            "error": "signature_not_found",
        }


# ---------------------------------------------------------------------------
# Idempotence -- already terminal
# ---------------------------------------------------------------------------
class TestIdempotence:
    def test_already_signed_short_circuits(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(stage="signed")
        _wire(h, monkeypatch, row=row)
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["ok"] is True
        assert resp["skipped"] is True
        row.mark_signed.assert_not_called()
        row.mark_failed.assert_not_called()

    def test_already_failed_short_circuits(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(stage="failed")
        _wire(h, monkeypatch, row=row)
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["skipped"] is True
        row.mark_signed.assert_not_called()

    def test_wrong_stage_returns_bad_stage(self, load_handler, monkeypatch):
        """The row is not terminal but also not 'signing' -- someone
        replayed the invoke by hand from an earlier stage."""
        h = load_handler(__file__)
        row = _fake_row(stage="otp")
        _wire(h, monkeypatch, row=row)
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp == {"ok": False, "error": "bad_stage", "stage": "otp"}


# ---------------------------------------------------------------------------
# Preconditions inside the pipeline
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_missing_signature_key_marks_failed(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(signature_key=None)
        _wire(h, monkeypatch, row=row)
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp == {"ok": False, "error": "missing_signature_key"}
        row.mark_failed.assert_called_once_with("missing_signature_key")

    def test_original_hash_mismatch_marks_failed(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        row = _fake_row(hash_original="00" * 32)  # deliberately wrong
        _wire(h, monkeypatch, row=row)
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["error"] == "original_pdf_tampered"
        row.mark_failed.assert_called_once_with("original_pdf_tampered")


# ---------------------------------------------------------------------------
# Failure at each pipeline step -> mark_failed(<stable code>)
# ---------------------------------------------------------------------------
class TestPipelineFailures:
    def test_cert_issuance_failure(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            issue_raises=RuntimeError("SSM boom"),
        )
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["error"] == "cert_issuance_failed"
        row.mark_failed.assert_called_once_with("cert_issuance_failed")

    def test_stamp_failure(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            stamp_raises=ValueError("page out of range"),
        )
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["error"] == "stamp_failed"
        row.mark_failed.assert_called_once_with("stamp_failed")

    def test_pades_signing_failure(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            sign_raises=RuntimeError("pyhanko boom"),
        )
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["error"] == "pades_signing_failed"
        row.mark_failed.assert_called_once_with("pades_signing_failed")

    def test_unexpected_exception_marks_internal_error(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(h, monkeypatch, row=row)
        monkeypatch.setattr(
            h,
            "_sha256",
            MagicMock(side_effect=Exception("boom")),
        )
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["error"] == "internal_error"
        row.mark_failed.assert_called_once_with("internal_error")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_signs_and_uploads(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        s3 = _wire(h, monkeypatch, row=row)
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["ok"] is True
        assert resp["cert_serial"] == _FAKE_SERIAL
        assert resp["hash_signed"] == hashlib.sha256(_FAKE_SIGNED_PDF).hexdigest()

        # Signed PDF and evidence package were uploaded to the expected
        # S3 keys.
        uploaded = s3.dump()
        assert "transactions/sign_abc/signed.pdf" in uploaded
        assert uploaded["transactions/sign_abc/signed.pdf"] == _FAKE_SIGNED_PDF
        pkg_key = "transactions/sign_abc/evidence-package.json"
        assert pkg_key in uploaded

        # Evidence package embeds the leaf cert + both hashes.
        import json

        pkg = json.loads(uploaded[pkg_key])
        assert pkg["sign_id"] == "sign_abc"
        assert pkg["signature"]["cert_serial"] == _FAKE_SERIAL
        assert pkg["document"]["hash_signed"] == resp["hash_signed"]
        assert pkg["document"]["hash_original"] == row.hash_original
        assert _FAKE_CERT_PEM.decode() in pkg["signature"]["cert_pem"]

        # Row was marked signed.
        row.mark_signed.assert_called_once()
        _, kw = row.mark_signed.call_args
        assert kw["cert_serial"] == _FAKE_SERIAL
        row.mark_failed.assert_not_called()

    def test_no_callback_url_skips_post(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(callback_url=None)
        _wire(h, monkeypatch, row=row, callback_resp=200)
        h.handler({"sign_id": "sign_abc"}, None)
        row.record_callback.assert_not_called()


# ---------------------------------------------------------------------------
# Callback (best-effort)
# ---------------------------------------------------------------------------
class TestCallback:
    def test_callback_success_records_sent(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(callback_url="https://example.com/webhook")
        _wire(h, monkeypatch, row=row, callback_resp=204)
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["ok"] is True
        # Sync mock: record_callback called with sent=True.
        row.record_callback.assert_called_once()
        _, kw = row.record_callback.call_args
        assert kw["sent"] is True

    def test_callback_non_2xx_records_http_status(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        row = _fake_row(callback_url="https://example.com/webhook")
        _wire(h, monkeypatch, row=row, callback_resp=500)
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["ok"] is True  # signed OK regardless of webhook outcome
        _, kw = row.record_callback.call_args
        assert kw["sent"] is False
        assert "500" in kw["error"]

    def test_callback_network_error_records_http_error(
        self, load_handler, monkeypatch
    ):
        import requests

        h = load_handler(__file__)
        row = _fake_row(callback_url="https://example.com/webhook")
        _wire(
            h,
            monkeypatch,
            row=row,
            callback_raises=requests.ConnectionError("no route to host"),
        )
        resp = h.handler({"sign_id": "sign_abc"}, None)
        assert resp["ok"] is True
        _, kw = row.record_callback.call_args
        assert kw["sent"] is False
        assert "http_error" in kw["error"]
