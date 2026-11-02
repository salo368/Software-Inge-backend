-- `draw_s3_key` holds the signer's drawn/uploaded signature image for
-- the SIGNATURE stage, set by `set_signature_draw`. Nullable: filled
-- once, after creation, same reasoning as the other *_s3_key columns.
--
-- Paired changes: libs/orm/signatures.py, services/signatures/src/
-- handlers/set_signature_draw (new).

-- +migrate up

ALTER TABLE signatures ADD COLUMN draw_s3_key VARCHAR(300);

-- +migrate down

ALTER TABLE signatures DROP COLUMN draw_s3_key;
