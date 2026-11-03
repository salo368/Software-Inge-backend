
import hashlib
import os
from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from libs.core.db import db_session
from libs.core.logger import Logger
from libs.core.s3 import download_bytes, upload_from_bytes
from libs.orm.signatures import SignatureStage, Signatures
from libs.utils.signature_audit_page import build_audit_page
from libs.utils.signature_ca import issue_transaction_cert, sign_pdf_pades_b
from libs.utils.signature_stamp import stamp_drawing_on_pdf

BUCKET = os.environ["SIGNATURES_BUCKET"]


def handler(event, context):
    signature_id = (event or {}).get("signature_id")
    if not signature_id:
        Logger.log("ERROR", "sign_doc: missing signature_id in payload")
        return {"ok": False, "error": "missing_signature_id"}

    row = Signatures.get_by_id(signature_id)
    if row is None:
        Logger.log("ERROR", f"sign_doc: no row for signature_id={signature_id}")
        return {"ok": False, "error": "signature_not_found"}

    if row.stage != SignatureStage.SIGNING.value:
        Logger.log(
            "WARNING",
            f"sign_doc: signature_id={signature_id} at stage={row.stage}, "
            "expected SIGNING; skipping (already handled or not ready)",
        )
        return {"ok": False, "skipped": True, "stage": row.stage}

    try:
        signed_s3_key = _run_pipeline(row)
        db_session.commit()
        Logger.log("INFO", f"sign_doc: signature_id={signature_id} completed -> {signed_s3_key}")
        return {"ok": True, "signature_id": str(signature_id), "signed_s3_key": signed_s3_key}
    except Exception as e:
        Logger.log("ERROR", f"sign_doc: signature_id={signature_id} crashed: {e}")
        db_session.rollback()
        return {"ok": False, "error": "internal_error"}
    finally:
        db_session.close()


def _run_pipeline(row) -> str:
    original_pdf = download_bytes(BUCKET, row.doc_s3_key)
    draw_png = download_bytes(BUCKET, row.draw_s3_key)
    id_front_png = download_bytes(BUCKET, row.id_front_s3_key)
    id_back_png = download_bytes(BUCKET, row.id_back_s3_key)
    face_png = download_bytes(BUCKET, row.id_face_s3_key)

    stamped_pdf = original_pdf
    for location in row.sign_location:
        stamped_pdf = stamp_drawing_on_pdf(stamped_pdf, draw_png, location)

    cert_pem, key_pem, cert_serial = issue_transaction_cert(
        signature_id=row.id,
        signer_email=row.email,
        signer_name=row.signatory,
    )

 
    doc_hash = hashlib.sha256(stamped_pdf).hexdigest()
    signed_at = datetime.now(timezone.utc)

    audit_page_pdf = build_audit_page(
        signature_id=str(row.id),
        signatory=row.signatory,
        email=row.email,
        id_front_png=id_front_png,
        id_back_png=id_back_png,
        face_png=face_png,
        draw_png=draw_png,
        signed_at=signed_at,
        cert_serial=cert_serial,
        document_hash=doc_hash,
        signing_data=row.signing_data,
    )
    combined_pdf = _append_page(stamped_pdf, audit_page_pdf)

    signed_pdf = sign_pdf_pades_b(combined_pdf, cert_pem, key_pem)
    signed_hash = hashlib.sha256(signed_pdf).hexdigest()

    # raw_signed is uploaded byte-for-byte as hashed: sha256 of the object
    # must equal doc_hash, the value printed inside the signed PDF.
    raw_signed_s3_key = f"signatures/{row.id}/raw_signed.pdf"
    signed_s3_key = f"signatures/{row.id}/signed.pdf"
    upload_from_bytes(BUCKET, raw_signed_s3_key, stamped_pdf, content_type="application/pdf")
    upload_from_bytes(BUCKET, signed_s3_key, signed_pdf, content_type="application/pdf")

    Signatures.mark_signed(
        row.id,
        signed_s3_key=signed_s3_key,
        raw_signed_s3_key=raw_signed_s3_key,
        doc_hash=doc_hash,
        signed_hash=signed_hash,
        signed_at=signed_at,
    )

    return signed_s3_key


def _append_page(base_pdf: bytes, extra_page_pdf: bytes) -> bytes:
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(base_pdf)))
    writer.append(PdfReader(BytesIO(extra_page_pdf)))
    out = BytesIO()
    writer.write(out)
    return out.getvalue()
