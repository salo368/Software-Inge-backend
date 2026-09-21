"""Advances a process to the next stage.

Stages: form -> documents -> signature -> payment -> done

Gates:
  form       : the user must have a Forms row (upserted via /forms/me).
               We snapshot it into process.form_snapshot.
  documents  : at least one file of type `declaracion_renta` must be
               present. On success we also OPEN the signature ceremony
               so the frontend can jump straight to signing on the same
               response (no extra round trip). See
               `utils.signature_bridge.open_ceremony_for_process`.
  signature  : a signature ceremony must have reached the `signed`
               stage. We look it up via `proc.sign_id` (populated by
               the previous transition); if `proc.sign_id` is missing
               the process was created before Fase 6a and cannot
               advance without a manual reopen.
  payment    : mocked. Any advance call moves it to `done`.
  done       : idempotent; returns the process untouched.

Response shape:

  {
    "process": <public_dict>,
    "sign_url": "<microfrontend URL>"     # only when we just opened
                                          # the ceremony (documents ->
                                          # signature transition)
  }
"""
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.banks import Banks
from libs.orm.files import Files
from libs.orm.forms import Forms
from libs.orm.processes import Processes
from libs.orm.signatures import Signatures
from libs.utils.auth import require_auth

from utils.signature_bridge import (
    SignatureBridgeError,
    open_ceremony_for_process,
)

NEXT_STAGE = {
    "form": "documents",
    "documents": "signature",
    "signature": "payment",
    "payment": "done",
}


@handle_exceptions
@require_auth
def handler(event, context):
    pid_raw = (event.get("pathParameters") or {}).get("id")
    try:
        pid = UUID(pid_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    proc = Processes.get_by_id(pid)
    if proc is None or proc.user_id != event["user"].id:
        raise HandledError("process_not_found", 404)

    if proc.stage == "done":
        return generate_response({"process": proc.public_dict()})

    # Extra keys the handler may add to the response BEFORE advance_to
    # commits. Right now the only one is `sign_url` produced when
    # opening the ceremony on the documents -> signature transition.
    extra: dict = {}

    if proc.stage == "form":
        form = Forms.get_by_user(event["user"].id)
        if form is None:
            raise HandledError("form_required", 400)
        proc.form_snapshot = form.public_dict()

    elif proc.stage == "documents":
        files = Files.list_by_process(proc.id)
        if not any(f.file_type == "declaracion_renta" for f in files):
            raise HandledError("declaracion_renta_required", 400)

        # Open the signature ceremony now. Rationale for doing it on
        # THIS transition instead of a dedicated endpoint: the frontend
        # already POSTs /processes/{id}/advance to move forward, so
        # returning `sign_url` in the same response keeps the wizard a
        # single request per step.
        bank = Banks.get_by_id(proc.bank_id)
        try:
            sign_url = open_ceremony_for_process(
                proc=proc, user=event["user"], bank=bank
            )
        except SignatureBridgeError as e:
            # 502 because the failure is downstream (signatures / S3);
            # the client should retry rather than treat it as a
            # validation error on its own payload.
            raise HandledError(f"signature_bridge_{e.code}", 502)
        extra["sign_url"] = sign_url

    elif proc.stage == "signature":
        if not proc.sign_id:
            # Process created BEFORE Fase 6a (no ceremony was ever
            # opened) OR the previous transition failed halfway. Force
            # the user to restart the flow rather than silently
            # skipping the signing step.
            raise HandledError("signature_required", 400)
        ceremony = Signatures.get_by_sign_id(proc.sign_id)
        if ceremony is None or ceremony.stage != "signed":
            raise HandledError("signature_required", 400)

    proc.advance_to(NEXT_STAGE[proc.stage])
    return generate_response({"process": proc.public_dict(), **extra})
