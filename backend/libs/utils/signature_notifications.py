
from __future__ import annotations

import json

from libs.core.logger import Logger
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_async


def notify_terminal_state(signature_id, stage: str, *, notify_signer: bool = False) -> None:
    payload = {"signature_id": str(signature_id)}

    try:
        invoke_async("sign_trigger", {**payload, "stage": stage})
    except LambdaInvokeError as e:
        Logger.log("ERROR", f"notify_terminal_state: sign_trigger invoke failed for {signature_id}: {e}")

    try:
        invoke_async("signed", {"body": json.dumps({**payload, "stage": stage})}, service="processes")
    except LambdaInvokeError as e:
        Logger.log("ERROR", f"notify_terminal_state: processes.signed invoke failed for {signature_id}: {e}")

    if notify_signer:
        try:
            invoke_async("notify_signed", payload)
        except LambdaInvokeError as e:
            Logger.log("ERROR", f"notify_terminal_state: notify_signed invoke failed for {signature_id}: {e}")
