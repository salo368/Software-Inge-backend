import os
from decimal import Decimal, InvalidOperation

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.banks import Banks
from libs.utils.rates import get_ranked_rates, yield_cop

ASSETS_BASE_URL = os.getenv("ASSETS_BASE_URL", "")

def _get_banks_data():

    banks = Banks.get_all(active=True)
    
    banks_data = {}
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
        banks_data[bank.id] = data

    return banks_data


@handle_exceptions
def handler(event, context):

    params = event.get("queryStringParameters") or {}
    amount = params.get("amount")
    term = params.get("term")

    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        raise HandledError("invalid_amount", 400)
    if amount <= 0:
        raise HandledError("invalid_amount", 400)

    try:
        term = int(term)
    except (ValueError, TypeError):
        raise HandledError("invalid_term", 400)
    if term <= 0:
        raise HandledError("invalid_term", 400)

    ranked = get_ranked_rates(amount, term)

    banks_data = _get_banks_data()

    banks_data_ranked = []

    for bank_id, rate in ranked:
        if bank_id in banks_data:
            interest, final = yield_cop(amount, rate, term)
            banks_data[bank_id]["rate"] = float(rate)
            banks_data[bank_id]["interest"] = float(interest)
            banks_data[bank_id]["final"] = float(final)
            banks_data_ranked.append(banks_data[bank_id])

    response = {
        "amount": float(amount),
        "term": term,
        "banks": banks_data_ranked,
    }

    return generate_response(response, 200)