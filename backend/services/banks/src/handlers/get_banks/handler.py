import os

from libs.core.responses import generate_response, handle_exceptions
from libs.orm.banks import Banks

ASSETS_BASE_URL = os.getenv("ASSETS_BASE_URL", "")


@handle_exceptions
def handler(event, context):

    banks = Banks.get_all(active=True)

    banks_data = []
    for bank in banks:
        data = {
            "id": bank.id,
            "code": bank.code,
            "name": bank.name,
            "logo_url": f"{ASSETS_BASE_URL.rstrip('/')}/{bank.logo_key}" if ASSETS_BASE_URL else bank.logo_key,
            "description": bank.description,
            "tier": bank.tier,
            "rating_by": bank.rating_by,
            "highlights": list(bank.highlights or []),
        }
        banks_data.append(data)

    response = {
        "banks": banks_data,
    }

    return generate_response(response, 200)
