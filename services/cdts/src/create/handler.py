from datetime import datetime, timezone

from utils.auth.middleware import require_auth
from utils.http import err, ok, parse_body
from utils.orm.models import Cdts


@require_auth
def create(event, context):
    body = parse_body(event)
    if body is None:
        return err(400, "invalid_json")

    amount = body.get("amount")
    term = body.get("term")
    rate = body.get("rate")
    if not amount or not term or rate is None:
        return err(400, "missing_fields", "amount, term y rate son requeridos")

    cdt = Cdts.create(
        user_id=event["auth"].user.id,
        stage="formularios",
        amount=amount,
        term=term,
        rate=rate,
        opened_at=datetime.now(timezone.utc),
    )
    return ok(201, cdt.to_dict())
