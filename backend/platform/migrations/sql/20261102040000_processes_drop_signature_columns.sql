-- Drops the leftover signature-flow columns from `processes` ahead of the
-- signatures refactor: `sign_id` (the old bridge to `signatures.sign_id`),
-- `signed_at`, `paid_at`, `completed_at`. Nothing currently reads or
-- writes them -- `advance`/`signature_callback` (the only callers) were
-- already removed earlier in this refactor. Clearing them now so the
-- upcoming signature redesign starts from a clean `processes` shape
-- instead of working around stale columns.

-- +migrate up

ALTER TABLE processes DROP COLUMN sign_id;
ALTER TABLE processes DROP COLUMN signed_at;
ALTER TABLE processes DROP COLUMN paid_at;
ALTER TABLE processes DROP COLUMN completed_at;

-- +migrate down

ALTER TABLE processes ADD COLUMN sign_id VARCHAR(64);
ALTER TABLE processes ADD COLUMN signed_at TIMESTAMPTZ;
ALTER TABLE processes ADD COLUMN paid_at TIMESTAMPTZ;
ALTER TABLE processes ADD COLUMN completed_at TIMESTAMPTZ;
