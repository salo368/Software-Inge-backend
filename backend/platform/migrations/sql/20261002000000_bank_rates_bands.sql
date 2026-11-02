-- Replaces bank_rates (bank_id, term_days, min_amount) -> rate with an
-- explicit range-band model: rates_term_band and rates_amount_band each hold a
-- [min, max] range per bank, and `rate` pairs one rates_term_band with one
-- rates_amount_band. No validity window for now -- rates are assumed not to
-- change; valid_from/valid_to can be added back when that stops being true.
--
-- This removes the old exact-match-on-term_days behaviour (a simulation
-- for 120 days used to match nothing) and the implicit open-ended last
-- amount bracket. Both axes are now explicit, bounded ranges, so any
-- (term_days, amount) either falls in exactly one band pair or in none.
--
-- The band boundaries are derived straight from the existing bank_rates
-- rows (LEAD() over each bank's distinct term_days / min_amount), so the
-- hand-tuned rate variety already seeded carries over untouched -- this
-- migration only reshapes the schema, it does not invent new numbers.
--
-- Paired changes:
--   * libs/orm/rates_term_band.py    (new)
--   * libs/orm/rates_amount_band.py  (new)
--   * libs/orm/rates.py        (new, replaces libs/orm/bank_rates.py)
--   * libs/orm/__init__.py
--   * services/banks/src/handlers/simulate/handler.py

-- +migrate up

CREATE TABLE rates_term_band (
    id          INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_id     INT           NOT NULL REFERENCES banks(id) ON DELETE CASCADE,
    min_days    INT           NOT NULL,
    max_days    INT           NOT NULL,
    UNIQUE (bank_id, min_days, max_days)
);

CREATE TABLE rates_amount_band (
    id          INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bank_id     INT           NOT NULL REFERENCES banks(id) ON DELETE CASCADE,
    min_amount  NUMERIC(15,2) NOT NULL,
    max_amount  NUMERIC(15,2) NOT NULL,
    UNIQUE (bank_id, min_amount, max_amount)
);

CREATE TABLE rate (
    term_band_id    INT          NOT NULL REFERENCES rates_term_band(id) ON DELETE CASCADE,
    amount_band_id  INT          NOT NULL REFERENCES rates_amount_band(id) ON DELETE CASCADE,
    rate            NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (term_band_id, amount_band_id)
);

-- Term bands: each bank's distinct term_days values become contiguous
-- bands -- upper edge = next distinct term_days minus 1 day; the last
-- (longest) band is left open at 9999 days (~27 years).
INSERT INTO rates_term_band (bank_id, min_days, max_days)
SELECT bank_id, min_days, COALESCE(next_min_days - 1, 9999)
FROM (
    SELECT bank_id, min_days,
           LEAD(min_days) OVER (PARTITION BY bank_id ORDER BY min_days) AS next_min_days
    FROM (SELECT DISTINCT bank_id, term_days AS min_days FROM bank_rates) d
) t;

-- Amount bands: same idea per bank, using each bank's own distinct
-- min_amount floors -- the last (highest) band is left open at a
-- practically-infinite ceiling.
INSERT INTO rates_amount_band (bank_id, min_amount, max_amount)
SELECT bank_id, min_amount, COALESCE(next_min_amount - 0.01, 9999999999.99)
FROM (
    SELECT bank_id, min_amount,
           LEAD(min_amount) OVER (PARTITION BY bank_id ORDER BY min_amount) AS next_min_amount
    FROM (SELECT DISTINCT bank_id, min_amount FROM bank_rates) d
) a;

-- Rates: join each old (bank, term_days, min_amount) row to the band ids
-- that now cover it, carrying the exact same hand-tuned rate forward.
INSERT INTO rate (term_band_id, amount_band_id, rate)
SELECT tb.id, ab.id, br.rate
FROM bank_rates br
JOIN rates_term_band tb
    ON tb.bank_id = br.bank_id AND br.term_days BETWEEN tb.min_days AND tb.max_days
JOIN rates_amount_band ab
    ON ab.bank_id = br.bank_id AND br.min_amount BETWEEN ab.min_amount AND ab.max_amount;

DROP TABLE bank_rates;

-- +migrate down

DROP TABLE IF EXISTS rate;
DROP TABLE IF EXISTS rates_amount_band;
DROP TABLE IF EXISTS rates_term_band;
