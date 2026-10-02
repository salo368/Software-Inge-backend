import math
from decimal import Decimal

from libs.orm.rates import Rate
from libs.orm.rates_amount_band import AmountBand
from libs.orm.rates_term_band import TermBand


def get_ranked_rates(amount: Decimal, term_days: int) -> list[tuple[int, Decimal]]:
    """[(bank_id, rate), ...] best rate first, for banks whose amount_band
    and term_band both cover (amount, term_days)."""

    amount_band_by_bank = {ab.bank_id: ab.id for ab in AmountBand.get_all_by_amount(amount)}
    term_band_by_bank = {tb.bank_id: tb.id for tb in TermBand.get_all_by_term(term_days)}

    band_pairs = [
        (amount_band_by_bank[bank_id], term_band_by_bank[bank_id])
        for bank_id in amount_band_by_bank.keys() & term_band_by_bank.keys()
    ]

    return Rate.get_all_by_bands(band_pairs)


def yield_cop(amount: Decimal, ea_pct: Decimal, days: int) -> tuple[Decimal, Decimal]:
    """Compound EAR yield over `days` (365-day base). Returns (interest, final)."""

    r = float(ea_pct) / 100.0
    years = days / 365.0
    final = Decimal(str(float(amount) * math.pow(1 + r, years)))
    interest = final - amount
    return interest.quantize(Decimal("0.01")), final.quantize(Decimal("0.01"))
