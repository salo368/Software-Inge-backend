"""SQS consumer for the short SIGNING safety net.

`resolve_otp` enqueues one message per signature with
DelaySeconds=SIGNING_TIMEOUT (60s) right when it hands the row off to
`sign_doc`. By the time this fires, sign_doc either finished
(stage=SIGNED) or it didn't -- crashed, hung, or never got invoked --
in which case we flip the row to FAILED. sign_doc itself never marks a
signature FAILED on its own errors (an internal failure isn't the
signer's fault); this worker is the only thing that does, for this stage.
"""
import json

from libs.core.db import db_session
from libs.core.logger import Logger
from libs.orm.signatures import SignatureStage, Signatures


def handler(event, context):
    for record in event.get("Records", []):
        try:
            _process_record(record)
        except Exception as e:
            Logger.log("ERROR", f"check_signing_timeout failed for {record}: {e}")
    db_session.commit()
    return {"processed": len(event.get("Records", []))}


def _process_record(record: dict) -> None:
    body = json.loads(record["body"])
    signature_id = body["signature_id"]

    row = Signatures.get_by_id(signature_id)
    if row is None:
        Logger.log("WARNING", f"check_signing_timeout: signature {signature_id} not found")
        return

    if row.stage != SignatureStage.SIGNING.value:
        return

    Signatures.mark_failed(signature_id)
    Logger.log("INFO", f"check_signing_timeout: marked {signature_id} FAILED (sign_doc never completed)")
