-- banks.min_amount was the bank's single floor investment amount. Now that
-- rates_amount_band holds a full [min,max] range per bank (introduced in
-- 20261002000000_bank_rates_bands.sql), that column is a second, divergeable
-- source of truth for the same fact -- drop it.
--
-- Paired changes:
--   * libs/orm/banks.py
--   * services/banks/src/handlers/get_banks/handler.py
--   * services/banks/src/handlers/simulate/handler.py

-- +migrate up

ALTER TABLE banks DROP COLUMN min_amount;

-- +migrate down

ALTER TABLE banks ADD COLUMN min_amount NUMERIC(15,2);

UPDATE banks b
SET min_amount = (
    SELECT MIN(ab.min_amount) FROM rates_amount_band ab WHERE ab.bank_id = b.id
);

ALTER TABLE banks ALTER COLUMN min_amount SET NOT NULL;
