from utils.auth.middleware import require_auth
from utils.http import ok
from utils.orm.models import Cdts


@require_auth
def list_cdts(event, context):
    rows = Cdts.get_by_user_id(event["auth"].user.id)
    rows.sort(key=lambda r: r.id, reverse=True)
    return ok(200, [r.to_dict() for r in rows])
