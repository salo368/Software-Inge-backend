-- `raw_signed_s3_key`: the document with the drawing stamped, no evidence
-- page and no PAdES signature -- the one exposed publicly by get_signature.
-- `doc_hash`: sha256 of raw_signed_s3_key's bytes; it's printed on the
-- evidence page, so it's covered by the PAdES signature of the final PDF.
-- `signed_hash`: sha256 of signed_s3_key's bytes (the final PDF), for a
-- public integrity check of the full file.
-- `signed_at`: same timestamp printed on the evidence page.
--
-- Paired changes: libs/orm/signatures.py, services/signatures/src/workers/
-- sign_doc, services/signatures/src/handlers/get_signature.

-- +migrate up

ALTER TABLE signatures ADD COLUMN raw_signed_s3_key VARCHAR(300);
ALTER TABLE signatures ADD COLUMN doc_hash VARCHAR(64);
ALTER TABLE signatures ADD COLUMN signed_hash VARCHAR(64);
ALTER TABLE signatures ADD COLUMN signed_at TIMESTAMPTZ;

-- +migrate down

ALTER TABLE signatures DROP COLUMN raw_signed_s3_key;
ALTER TABLE signatures DROP COLUMN doc_hash;
ALTER TABLE signatures DROP COLUMN signed_hash;
ALTER TABLE signatures DROP COLUMN signed_at;
