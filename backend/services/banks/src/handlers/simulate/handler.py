import json
import math
import os
from decimal import Decimal, InvalidOperation

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.bank_rates import BankRates
from libs.orm.banks import Banks

ASSETS_BASE_URL = os.getenv("ASSETS_BASE_URL", "")

VALID_TERMS = {90, 180, 360, 540, 720}


def _parse_amount(raw) -> Decimal:
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise HandledError("invalid_amount", 400)
    if amount <= 0:
        raise HandledError("invalid_amount", 400)
    return amount


def _parse_term(raw) -> int:
    try:
        term = int(raw)
    except (ValueError, TypeError):
        raise HandledError("invalid_term_days", 400)
    if term not in VALID_TERMS:
        raise HandledError("invalid_term_days", 400)
    return term


def _yield_cop(amount: Decimal, ea_pct: Decimal, days: int) -> tuple[Decimal, Decimal]:
    """Compound EAR yield over `days` (365-day base). Returns (interest, total)."""
    r = float(ea_pct) / 100.0
    years = days / 365.0
    final = Decimal(str(float(amount) * math.pow(1 + r, years)))
    interest = final - amount
    return interest.quantize(Decimal("0.01")), final.quantize(Decimal("0.01"))


@handle_exceptions
def handler(event, context):
    body = json.loads(event.get("body") or "{}")
    amount = _parse_amount(body.get("amount"))
    term_days = _parse_term(body.get("term_days"))

    rates_by_bank = BankRates.best_per_bank(term_days, amount)
    banks = Banks.list_active()

    results = []
    for bank in banks:
        rate = rates_by_bank.get(bank.id)
        if rate is None:
            # Skip banks whose floor is above `amount` (no bracket applies).
            continue
        interest, final = _yield_cop(amount, rate, term_days)
        results.append({
            "bank": bank.public_dict(ASSETS_BASE_URL),
            "rate": float(rate),
            "interest": float(interest),
            "final": float(final),
        })

    results.sort(key=lambda r: r["rate"], reverse=True)

    return generate_response({
        "amount": float(amount),
        "term_days": term_days,
        "results": results,
    })
