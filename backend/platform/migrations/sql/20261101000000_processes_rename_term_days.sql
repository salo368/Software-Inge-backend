-- Renames `processes.term_days` to `processes.term`. The unit is always
-- days (see `rates_term_band.min_days`/`max_days`); the `_days` suffix was
-- redundant everywhere the column was used.

-- +migrate up

ALTER TABLE processes RENAME COLUMN term_days TO term;

-- +migrate down

ALTER TABLE processes RENAME COLUMN term TO term_days;
