"""Fires the post-signature notifications from every place that sets a
terminal stage (SIGNED or FAILED): sign_doc (SIGNED), and resolve_otp /
check_signature_timeout / check_signing_timeout (FAILED). Centralized
here so those four call sites can't drift out of sync with each other.

`sign_trigger` fires for both terminal stages; `notify_signed` (the
"you signed a document" email) only fires on SIGNED.

Best-effort: a failed invoke_async *submission* is logged, never raised
-- the signature's own state transition must not be undone by a
notification plumbing hiccup. (The invoked lambda's own outcome is
separately best-effort inside itself.)
"""
from __future__ import annotations

from libs.core.logger import Logger
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_async


def notify_terminal_state(signature_id, stage: str, *, notify_signer: bool = False) -> None:
    payload = {"signature_id": str(signature_id)}

    try:
        invoke_async("sign_trigger", {**payload, "stage": stage})
    except LambdaInvokeError as e:
        Logger.log("ERROR", f"notify_terminal_state: sign_trigger invoke failed for {signature_id}: {e}")

    if notify_signer:
        try:
            invoke_async("notify_signed", payload)
        except LambdaInvokeError as e:
            Logger.log("ERROR", f"notify_terminal_state: notify_signed invoke failed for {signature_id}: {e}")
