import os

from libs.core.responses import generate_response, handle_exceptions
from libs.orm.banks import Banks

ASSETS_BASE_URL = os.getenv("ASSETS_BASE_URL", "")


@handle_exceptions
def handler(event, context):
    # Lists active banks with their logo URLs resolved against ASSETS_BASE_URL.
    banks = Banks.list_active()
    return generate_response({
        "banks": [b.public_dict(ASSETS_BASE_URL) for b in banks],
    })
