-- OTP step: `otp_hash` (SHA-256 of the current code, single-use --
-- cleared once verified), `otp_at` (when the current code was issued,
-- the clock `resolve_otp` checks the 2-minute TTL against) and
-- `otp_tries` (failed resolve_otp attempts against the CURRENT code;
-- reset to 0 every time set_otp issues/resends a code).
--
-- `otp_tries` can safely be NOT NULL DEFAULT 0 even though `signatures`
-- already has rows -- unlike the `signatory` incident, a constant
-- default doesn't require a table rewrite.
--
-- Paired changes: libs/orm/signatures.py (FAILED stage, SIGNING_WINDOW
-- now 15 min to match the SQS timeout below, OTP_TTL, MAX_OTP_TRIES),
-- services/signatures/src/handlers/{set_otp,resolve_otp} (new),
-- services/signatures/src/workers/check_signature_timeout (new).

-- +migrate up

ALTER TABLE signatures ADD COLUMN otp_hash VARCHAR(64);
ALTER TABLE signatures ADD COLUMN otp_at TIMESTAMPTZ;
ALTER TABLE signatures ADD COLUMN otp_tries INT NOT NULL DEFAULT 0;

-- +migrate down

ALTER TABLE signatures DROP COLUMN otp_hash;
ALTER TABLE signatures DROP COLUMN otp_at;
ALTER TABLE signatures DROP COLUMN otp_tries;
