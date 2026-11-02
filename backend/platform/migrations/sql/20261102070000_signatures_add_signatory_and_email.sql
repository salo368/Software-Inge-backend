-- `signatory` (the signer's full name) is collected at `create_signature`
-- time, so it's required from the start. `email` is only known once the
-- FORM stage is completed via `set_signature_form`, so it starts out NULL.
--
-- Assumes `signatures` is empty at migration time (dev-only, same
-- assumption as the v3 rewrite) -- that's why `signatory` can be NOT NULL
-- without a backfill default.
--
-- Paired changes: libs/orm/signatures.py, services/signatures/src/handlers/
-- create_signature (now requires signatory), set_signature_form (new).

-- +migrate up

ALTER TABLE signatures ADD COLUMN signatory VARCHAR(200) NOT NULL;
ALTER TABLE signatures ADD COLUMN email VARCHAR(320);

-- +migrate down

ALTER TABLE signatures DROP COLUMN signatory;
ALTER TABLE signatures DROP COLUMN email;
