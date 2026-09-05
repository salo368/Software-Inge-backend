from utils.auth.middleware import require_auth
from utils.http import err, ok
from utils.orm.models import Cdts


@require_auth
def get_cdt(event, context):
    try:
        cdt_id = int(event["pathParameters"]["id"])
    except (KeyError, ValueError):
        return err(404, "cdt_not_found")

    cdt = Cdts.get_by_id(cdt_id)
    if cdt is None or cdt.user_id != event["auth"].user.id:
        return err(404, "cdt_not_found")
    return ok(200, cdt.to_dict())
