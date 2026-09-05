from utils.auth.middleware import require_auth
from utils.http import err, ok
from utils.orm.models import Cdts

STAGES = ["formularios", "documentos", "firma", "pago", "terminado"]


@require_auth
def advance(event, context):
    try:
        cdt_id = int(event["pathParameters"]["id"])
    except (KeyError, ValueError):
        return err(404, "cdt_not_found")

    cdt = Cdts.get_by_id(cdt_id)
    if cdt is None or cdt.user_id != event["auth"].user.id:
        return err(404, "cdt_not_found")

    idx = STAGES.index(cdt.stage)
    if idx >= len(STAGES) - 1:
        return err(409, "already_finished")

    updated = Cdts.update_by_id(cdt.id, {"stage": STAGES[idx + 1]})
    return ok(200, updated.to_dict())
