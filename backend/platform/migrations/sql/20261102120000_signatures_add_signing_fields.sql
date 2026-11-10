-- `signed_s3_key` is the final PDF (crypto-signed + audit page appended)
-- that `sign_doc` produces. `signing_data` is a JSON grab-bag of request
-- telemetry (IP, user agent, etc.) captured by `resolve_otp` at the
-- moment it flips a signature to SIGNING, so `sign_doc` -- which runs
-- async, detached from the original HTTP request -- can still render
-- that telemetry onto the audit page.
--
-- Paired changes: libs/orm/signatures.py (SIGNING stage, new columns,
-- start_signing/mark_signed), libs/utils/{signature_ca,signature_stamp,
-- signature_audit_page}.py (new), services/signatures/src/handlers/
-- resolve_otp (now stops at SIGNING), services/signatures/src/workers/
-- {sign_doc,check_signing_timeout} (new).

-- +migrate up

ALTER TABLE signatures ADD COLUMN signed_s3_key VARCHAR(300);
ALTER TABLE signatures ADD COLUMN signing_data JSONB;

-- +migrate down

ALTER TABLE signatures DROP COLUMN signed_s3_key;
ALTER TABLE signatures DROP COLUMN signing_data;
