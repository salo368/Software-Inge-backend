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
from libs.utils.signature_notifications import notify_terminal_state


def handler(event, context):
    # Notifications fire only after the batch commit below succeeds --
    # never for a FAILED write that might not have actually persisted.
    newly_failed = []
    for record in event.get("Records", []):
        try:
            signature_id = _process_record(record)
            if signature_id is not None:
                newly_failed.append(signature_id)
        except Exception as e:
            Logger.log("ERROR", f"check_signing_timeout failed for {record}: {e}")
    db_session.commit()
    for signature_id in newly_failed:
        notify_terminal_state(signature_id, "FAILED")
    return {"processed": len(event.get("Records", []))}


def _process_record(record: dict):
    body = json.loads(record["body"])
    signature_id = body["signature_id"]

    row = Signatures.get_by_id(signature_id)
    if row is None:
        Logger.log("WARNING", f"check_signing_timeout: signature {signature_id} not found")
        return None

    if row.stage != SignatureStage.SIGNING.value:
        return None

    Signatures.mark_failed(signature_id)
    Logger.log("INFO", f"check_signing_timeout: marked {signature_id} FAILED (sign_doc never completed)")
    return signature_id
