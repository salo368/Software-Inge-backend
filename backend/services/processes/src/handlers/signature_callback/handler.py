"""Webhook receiver for signatures.

Contract with `signatures.sign`:

    POST /processes/signature-callback
    Content-Type: application/json

    {
        "sign_id":     "<32-byte urlsafe token>",  # required
        "stage":       "signed" | "failed" | ...,  # informational only
        "hash_signed": "...",                      # informational only
        "signed_at":   "2026-...+00:00",           # informational only
        "cert_serial": "..."                       # informational only
    }

Design decisions:

* **Auth model = zero trust.** The payload above is a WAKEUP SIGNAL,
  not a source of truth. We take `sign_id`, throw the rest away, and
  re-read the ceremony directly from `Signatures.get_by_sign_id`. An
  attacker with a random sign_id gets a no-op (unknown ceremony); an
  attacker guessing a real sign_id still cannot forge the ceremony's
  `stage` because we ignore what they sent.

* **Signatures does not know about processes.** It just POSTs to
  whatever `callback_url` the ceremony was created with. So we route
  by `sign_id`, not by a process id in the URL.

* **Idempotent.** signatures may retry the webhook on transient
  network errors. `mark_signed_at` no-ops after the first successful
  stamp; the auto-advance decision reads the CURRENT stage so a second
  callback while we're already past `signature` is silently ignored.

* **We do NOT auto-advance to `payment`.** The user must click
  "advance" so the wizard flows through the mocked payment step; the
  callback's only DB effect is stamping `signed_at` (unlocks the
  advance button and makes the audit trail accurate).

Response is always 200 (webhook contract):

    {"ok": true, "action": "<what we did>"}

    action ∈ {
        "signed_marked"     # ceremony=signed, we stamped signed_at
        "already_marked"    # ceremony=signed, we had already stamped
        "ceremony_failed"   # ceremony=failed/expired, we logged, no-op
        "ceremony_pending"  # ceremony still mid-flow (unexpected), no-op
        "process_not_found" # sign_id doesn't map to any process (stale
                            # callback OR foreign env); silent no-op
        "signature_not_found"
    }

We deliberately return 200 with `action` rather than 4xx even for
missing sign_ids so a retry storm from a misdirected webhook does not
generate operator noise upstream.
"""

from __future__ import annotations

import json

from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.processes import Processes
from libs.orm.signatures import Signatures


@handle_exceptions
def handler(event, context):
    body = json.loads(event.get("body") or "{}")
    sign_id = body.get("sign_id")

    if not isinstance(sign_id, str) or not sign_id.strip():
        raise HandledError("missing_sign_id", 400)
    sign_id = sign_id.strip()

    proc = Processes.get_by_sign_id(sign_id)
    if proc is None:
        # Stale callback or hostile caller. Not our ceremony.
        Logger.log(
            "WARNING",
            f"signature_callback: no process for sign_id={sign_id[:6]}",
        )
        return generate_response({"ok": True, "action": "process_not_found"})

    ceremony = Signatures.get_by_sign_id(sign_id)
    if ceremony is None:
        # Very unusual: process bound to a sign_id but no ceremony row.
        # Likely means the signatures DB was wiped in dev; we can't
        # advance the process from this side.
        Logger.log(
            "ERROR",
            f"signature_callback: process={proc.id} bound to sign_id={sign_id[:6]} "
            f"but no ceremony row exists",
        )
        return generate_response({"ok": True, "action": "signature_not_found"})

    if ceremony.stage == "signed":
        already = proc.signed_at is not None
        proc.mark_signed_at(ceremony.signed_at)
        action = "already_marked" if already else "signed_marked"
        Logger.log(
            "INFO",
            f"signature_callback: process={proc.id} sign_id={sign_id[:6]} "
            f"{action} (ceremony signed_at={ceremony.signed_at})",
        )
        return generate_response({"ok": True, "action": action})

    if ceremony.stage in ("failed", "expired"):
        # Ceremony didn't complete. Leave the process in `signature`
        # so the UI can show the failure and offer a retry path;
        # touching stage here would mask the failure from the user.
        Logger.log(
            "WARNING",
            f"signature_callback: process={proc.id} sign_id={sign_id[:6]} "
            f"ceremony ended in stage={ceremony.stage}",
        )
        return generate_response({"ok": True, "action": "ceremony_failed"})

    # Any other stage means signatures fired the webhook mid-flow --
    # not something the current `sign` handler does, but we defend
    # against future protocol changes by returning 200 without touching
    # state.
    Logger.log(
        "WARNING",
        f"signature_callback: process={proc.id} sign_id={sign_id[:6]} "
        f"unexpected ceremony stage={ceremony.stage}",
    )
    return generate_response({"ok": True, "action": "ceremony_pending"})
