"""SQS consumer for the 15-minute signing-window safety net.

`create_signature` enqueues one message per signature with
DelaySeconds=SIGNING_WINDOW (900s). By the time this fires, the signer
either finished (stage=SIGNED) or didn't -- in which case we actively
flip the row to FAILED instead of leaving it stuck wherever it was,
so no ceremony is left dangling forever without a terminal stage.
"""
import json

from libs.core.db import db_session
from libs.core.logger import Logger
from libs.orm.signatures import SignatureStage, Signatures

_TERMINAL_STAGES = (SignatureStage.SIGNED.value, SignatureStage.FAILED.value)


def handler(event, context):
    for record in event.get("Records", []):
        try:
            _process_record(record)
        except Exception as e:
            Logger.log("ERROR", f"check_signature_timeout failed for {record}: {e}")
    db_session.commit()
    return {"processed": len(event.get("Records", []))}


def _process_record(record: dict) -> None:
    body = json.loads(record["body"])
    signature_id = body["signature_id"]

    row = Signatures.get_by_id(signature_id)
    if row is None:
        Logger.log("WARNING", f"check_signature_timeout: signature {signature_id} not found")
        return

    if row.stage in _TERMINAL_STAGES:
        return

    Signatures.mark_failed(signature_id)
    Logger.log("INFO", f"check_signature_timeout: marked {signature_id} FAILED (was {row.stage})")
