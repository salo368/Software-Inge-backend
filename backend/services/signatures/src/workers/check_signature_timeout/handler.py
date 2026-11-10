"""SQS consumer for the 15-minute signing-window safety net.

`create_signature` enqueues one message per signature with
DelaySeconds=SIGNING_WINDOW (900s). By the time this fires, the signer
either finished (stage=SIGNED) or didn't -- in which case we actively
flip the row to FAILED instead of leaving it stuck wherever it was,
so no ceremony is left dangling forever without a terminal stage.

SIGNING is deliberately left alone here: once resolve_otp hands a
signature off to sign_doc, check_signing_timeout (a separate, much
shorter-delay queue) owns deciding whether that specific step failed.
Touching SIGNING from both workers would race.
"""
import json

from libs.core.db import db_session
from libs.core.logger import Logger
from libs.orm.signatures import SignatureStage, Signatures
from libs.utils.signature_notifications import notify_terminal_state

_SKIP_STAGES = (
    SignatureStage.SIGNED.value,
    SignatureStage.FAILED.value,
    SignatureStage.SIGNING.value,
)


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
            Logger.log("ERROR", f"check_signature_timeout failed for {record}: {e}")
    db_session.commit()
    for signature_id in newly_failed:
        notify_terminal_state(signature_id, "FAILED")
    return {"processed": len(event.get("Records", []))}


def _process_record(record: dict):
    body = json.loads(record["body"])
    signature_id = body["signature_id"]

    row = Signatures.get_by_id(signature_id)
    if row is None:
        Logger.log("WARNING", f"check_signature_timeout: signature {signature_id} not found")
        return None

    if row.stage in _SKIP_STAGES:
        return None

    Signatures.mark_failed(signature_id)
    Logger.log("INFO", f"check_signature_timeout: marked {signature_id} FAILED (was {row.stage})")
    return signature_id
