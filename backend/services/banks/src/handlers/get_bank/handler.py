import os

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.banks import Banks

ASSETS_BASE_URL = os.getenv("ASSETS_BASE_URL", "")


def _asset_url(key):
    if not key:
        return None
    return f"{ASSETS_BASE_URL.rstrip('/')}/{key}" if ASSETS_BASE_URL else key


@handle_exceptions
def handler(event, context):

    query_params = event.get("queryStringParameters") or {}

    bank_id_raw = query_params.get("bank_id")
    try:
        bank_id = int(bank_id_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid bank_id", 400)

    bank = Banks.get_by_id(bank_id)
    if bank is None:
        raise HandledError("bank_not_found", 404)

    response = {
        "id": bank.id,
        "code": bank.code,
        "name": bank.name,
        "logo_url": _asset_url(bank.logo_key),
        "io_url": _asset_url(bank.io_key),
        "description": bank.description,
        "tier": bank.tier,
        "rating_by": bank.rating_by,
        "highlights": list(bank.highlights or []),
        "is_active": bank.is_active,
    }

    return generate_response(response, 200)
