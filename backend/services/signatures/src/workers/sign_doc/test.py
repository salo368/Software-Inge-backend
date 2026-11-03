"""Unit tests for the signatures sign_doc internal worker."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call
from uuid import uuid4


def _row(stage="SIGNING", **overrides):
    defaults = dict(
        id=str(uuid4()),
        stage=stage,
        doc_s3_key="original.pdf",
        draw_s3_key="draw.png",
        id_front_s3_key="id_front.jpg",
        id_back_s3_key="id_back.jpg",
        id_face_s3_key="face.jpg",
        sign_location=[{"page": 1, "x_pct": 9.0, "y_pct": 87.5, "width_pct": 28.0}],
        signatory="Juan Perez",
        email="juan@example.com",
        signing_data={"ip": "1.2.3.4"},
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _patch_pipeline(h, monkeypatch, **overrides):
    mocks = dict(
        download_bytes=MagicMock(side_effect=lambda bucket, key: f"bytes:{key}".encode()),
        stamp_drawing_on_pdf=MagicMock(side_effect=lambda pdf, draw, loc: pdf + b":stamped"),
        issue_transaction_cert=MagicMock(return_value=(b"cert-pem", b"key-pem", "serial123")),
        sign_pdf_pades_b=MagicMock(return_value=b"signed-pdf-bytes"),
        build_audit_page=MagicMock(return_value=b"%PDF-1.4 audit"),
        upload_from_bytes=MagicMock(),
        db_session=MagicMock(),
    )
    mocks.update(overrides)
    for name, mock in mocks.items():
        monkeypatch.setattr(h, name, mock)
    return mocks


def test_sign_doc_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row()
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_signed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    mocks = _patch_pipeline(h, monkeypatch)

    # _append_page needs real PDF bytes, not the pipeline's fake tokens --
    # stub it directly so the test isn't coupled to pypdf internals. It
    # must run BEFORE sign_pdf_pades_b (the audit page has to be inside
    # what gets signed, not appended after -- see sign_doc's docstring).
    monkeypatch.setattr(h, "_append_page", MagicMock(return_value=b"combined-pdf"))

    result = h.handler({"signature_id": row.id}, None)

    assert result["ok"] is True
    assert result["signed_s3_key"] == f"signatures/{row.id}/signed.pdf"

    mocks["issue_transaction_cert"].assert_called_once_with(
        signature_id=row.id, signer_email=row.email, signer_name=row.signatory,
    )
    # sign_pdf_pades_b must be called with the COMBINED (stamped + audit
    # page) pdf, never with the pre-audit-page stamped pdf alone.
    mocks["sign_pdf_pades_b"].assert_called_once_with(b"combined-pdf", b"cert-pem", b"key-pem")

    mocks["upload_from_bytes"].assert_called_once()
    bucket, key, data = mocks["upload_from_bytes"].call_args.args
    assert key == f"signatures/{row.id}/signed.pdf"
    assert data == b"signed-pdf-bytes"
    assert mocks["upload_from_bytes"].call_args.kwargs["content_type"] == "application/pdf"

    signatures_mock.mark_signed.assert_called_once_with(row.id, f"signatures/{row.id}/signed.pdf")
    mocks["db_session"].commit.assert_called_once()
    mocks["db_session"].rollback.assert_not_called()


def test_sign_doc_stamps_once_per_sign_location_entry(load_handler, monkeypatch):
    h = load_handler(__file__)

    multi_page = [
        {"page": 1, "x_pct": 9.0, "y_pct": 87.5, "width_pct": 28.0},
        {"page": 2, "x_pct": 9.0, "y_pct": 87.5, "width_pct": 28.0},
    ]
    row = _row(sign_location=multi_page)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row), mark_signed=MagicMock()))
    mocks = _patch_pipeline(h, monkeypatch)
    monkeypatch.setattr(h, "_append_page", MagicMock(return_value=b"final-pdf"))

    h.handler({"signature_id": row.id}, None)

    assert mocks["stamp_drawing_on_pdf"].call_count == 2
    assert mocks["stamp_drawing_on_pdf"].call_args_list[0].args[2] == multi_page[0]
    assert mocks["stamp_drawing_on_pdf"].call_args_list[1].args[2] == multi_page[1]


def test_sign_doc_missing_signature_id_short_circuits(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    result = h.handler({}, None)

    assert result == {"ok": False, "error": "missing_signature_id"}


def test_sign_doc_not_found(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    result = h.handler({"signature_id": str(uuid4())}, None)

    assert result == {"ok": False, "error": "signature_not_found"}


def test_sign_doc_wrong_stage_is_skipped(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="SIGNED")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_signed=MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "download_bytes", MagicMock(side_effect=AssertionError))

    result = h.handler({"signature_id": row.id}, None)

    assert result == {"ok": False, "skipped": True, "stage": "SIGNED"}
    signatures_mock.mark_signed.assert_not_called()


def test_sign_doc_pipeline_failure_does_not_mark_failed(load_handler, monkeypatch):
    """The core design rule: an internal crash leaves the row at SIGNING.
    check_signing_timeout -- not sign_doc -- decides a stuck row failed."""
    h = load_handler(__file__)

    row = _row()
    signatures_mock = MagicMock(
        get_by_id=MagicMock(return_value=row),
        mark_signed=MagicMock(side_effect=AssertionError),
        mark_failed=MagicMock(side_effect=AssertionError),
    )
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    mocks = _patch_pipeline(h, monkeypatch, sign_pdf_pades_b=MagicMock(side_effect=RuntimeError("pyhanko exploded")))

    result = h.handler({"signature_id": row.id}, None)

    assert result == {"ok": False, "error": "internal_error"}
    signatures_mock.mark_signed.assert_not_called()
    signatures_mock.mark_failed.assert_not_called()
    mocks["db_session"].rollback.assert_called_once()
    mocks["db_session"].commit.assert_not_called()
