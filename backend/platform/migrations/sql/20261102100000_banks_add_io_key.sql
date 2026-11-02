-- `io_key` is the S3 key of the bank's "orden de inversion" (investment
-- order) PDF template under the assets bucket, same convention as
-- `logo_key` (relative key, ASSETS_BASE_URL is prepended at read time).
-- Nullable at the DB level (learned from the signatures.signatory
-- incident): an ADD COLUMN ... NOT NULL fails outright if the table
-- already has rows, which banks does.
--
-- Backfilled here for the 12 banks seeded in 20260920000000_banks.sql;
-- any bank added later must set io_key itself (no default).

-- +migrate up

ALTER TABLE banks ADD COLUMN io_key TEXT;

UPDATE banks SET io_key = 'order-forms/bancolombia.pdf' WHERE code = 'bancolombia';
UPDATE banks SET io_key = 'order-forms/davivienda.pdf' WHERE code = 'davivienda';
UPDATE banks SET io_key = 'order-forms/bbva.pdf' WHERE code = 'bbva';
UPDATE banks SET io_key = 'order-forms/bogota.pdf' WHERE code = 'bogota';
UPDATE banks SET io_key = 'order-forms/itau.pdf' WHERE code = 'itau';
UPDATE banks SET io_key = 'order-forms/scotiabank.pdf' WHERE code = 'scotiabank';
UPDATE banks SET io_key = 'order-forms/serfinanza.pdf' WHERE code = 'serfinanza';
UPDATE banks SET io_key = 'order-forms/pichincha.pdf' WHERE code = 'pichincha';
UPDATE banks SET io_key = 'order-forms/finandina.pdf' WHERE code = 'finandina';
UPDATE banks SET io_key = 'order-forms/pibank.pdf' WHERE code = 'pibank';
UPDATE banks SET io_key = 'order-forms/coltefinanciera.pdf' WHERE code = 'coltefinanciera';
UPDATE banks SET io_key = 'order-forms/nu.pdf' WHERE code = 'nu';

-- +migrate down

ALTER TABLE banks DROP COLUMN io_key;
