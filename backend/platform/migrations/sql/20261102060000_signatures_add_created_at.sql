-- Adds `created_at` to `signatures`, needed by `get_signature` to enforce
-- the 20-minute public signing window (created_at + 20 min = deadline).
--
-- Paired changes: libs/orm/signatures.py, services/signatures/src/handlers/
-- get_signature (new).

-- +migrate up

ALTER TABLE signatures ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- +migrate down

ALTER TABLE signatures DROP COLUMN created_at;
