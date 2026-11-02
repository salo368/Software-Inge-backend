-- `signatory` (the signer's full name) is collected at `create_signature`
-- time and `email` once the FORM stage is completed via
-- `set_signature_form`. Both are required at the application level, but
-- NOT NULL at the DB level would fail here: dev's `signatures` table
-- already has rows from manual testing, so a NOT NULL ADD COLUMN with no
-- default errors out (same nullable-but-app-required pattern already
-- used for `sign_location`).
--
-- Paired changes: libs/orm/signatures.py, services/signatures/src/handlers/
-- create_signature (now requires signatory), set_signature_form (new).

-- +migrate up

ALTER TABLE signatures ADD COLUMN signatory VARCHAR(200);
ALTER TABLE signatures ADD COLUMN email VARCHAR(320);

-- +migrate down

ALTER TABLE signatures DROP COLUMN signatory;
ALTER TABLE signatures DROP COLUMN email;
