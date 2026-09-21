-- Signatures v2: rewrite the ceremony schema so `signatures` is a fully
-- generic signing service (no coupling to processes, forms, banks, files).
--
-- Key differences vs `20260922000000_signatures.sql`:
--   * `sign_id` (TEXT) is the primary key AND the credential. Whoever
--     holds the URL that embeds it can operate the ceremony; that URL is
--     produced at `create` and shown to the signer via email.
--   * No FK to `processes`. The caller (any service, including a future
--     non-CDT flow) receives `sign_id` from `POST /signatures` and stores
--     it wherever it needs it. For our CDT flow, `processes.sign_id`
--     (added below) is that pointer.
--   * `signature_location` is stored as JSONB `{page, x_pct, y_pct}`
--     instead of three columns, so future flows can add coordinate
--     variants (multi-page signatures, anchors, etc.) without new
--     migrations.
--   * Explicit consent step: `consent_given_at` + `consent_terms_version`
--     are set by the `POST /signatures/{sign_id}/consent` endpoint before
--     OTP is issued. Ley 527/1999 wants authentication and consent to be
--     distinguishable in the audit trail.
--   * `hash_original` is set at `create` (SHA-256 of the source PDF),
--     `hash_signed` at `sign` (SHA-256 of the PAdES output).
--   * `cert_serial` tracks the ephemeral certificate issued by the Mock
--     CA for this transaction; the public cert PEM lives in the
--     evidence-package.json in S3.
--   * `expires_at` (24h from creation) lets a housekeeping job mark
--     abandoned ceremonies as `expired`. The partial index below scopes
--     that scan to non-terminal rows.
--   * `callback_url` / `callback_sent_at` / `callback_failed_at` /
--     `callback_error` capture the one-shot webhook attempt. No retry;
--     if the caller misses it, they can poll `GET /signatures/{sign_id}`.
--
-- This is a DESTRUCTIVE migration: all existing rows in `signatures` are
-- dropped (dev only). The `down` direction restores the old shape as a
-- best-effort rollback path.

-- +migrate up

DROP INDEX IF EXISTS signatures_process_id_idx;
DROP TABLE IF EXISTS signatures;

CREATE TABLE signatures (
    -- 32-byte urlsafe token as both id and capability. See libs/orm/signatures.py.
    sign_id                    VARCHAR(64)   PRIMARY KEY,
    signer_email               VARCHAR(320)  NOT NULL,
    signer_name                VARCHAR(200),
    -- {page: int (1-based), x_pct: 0-100, y_pct: 0-100}
    signature_location         JSONB         NOT NULL,
    -- Optional HTTPS webhook fired ONCE at the end of `sign`. One shot,
    -- no retry; on failure the caller falls back to polling GET.
    callback_url               TEXT,
    -- Which service called POST /signatures. Recorded for audit only.
    service_caller             VARCHAR(100),
    -- SHA-256 of the source PDF, captured at `create`. Used later by
    -- /verify to reject tampering claims.
    hash_original              VARCHAR(64)   NOT NULL,
    hash_signed                VARCHAR(64),
    -- Serial of the ephemeral cert the Mock CA issued for this
    -- transaction. The full cert PEM is embedded in the signed PDF and in
    -- evidence-package.json; here we only keep the pointer for lookups.
    cert_serial                VARCHAR(64),
    -- Lifecycle stage. See STAGES in libs/orm/signatures.py.
    stage                      VARCHAR(20)   NOT NULL DEFAULT 'created',
    -- Evidence S3 keys (relative to cdts-{stage}-signatures). Uploaded
    -- via presigned PUT before being validated.
    cedula_front_key           TEXT,
    cedula_back_key            TEXT,
    face_key                   TEXT,
    signature_key              TEXT,
    -- Rekognition validation timestamps. `signature_key` has no separate
    -- validated_at because it's just a canvas PNG (no biometric check).
    cedula_front_validated_at  TIMESTAMPTZ,
    cedula_back_validated_at   TIMESTAMPTZ,
    face_validated_at          TIMESTAMPTZ,
    -- Explicit consent step (Ley 527).
    consent_given_at           TIMESTAMPTZ,
    consent_terms_version      VARCHAR(50),
    -- OTP challenge (10 min TTL, 5 attempts; enforced in the ORM).
    otp_hash                   VARCHAR(64),
    otp_expires_at             TIMESTAMPTZ,
    otp_attempts               INT           NOT NULL DEFAULT 0,
    -- Terminal state.
    signed_at                  TIMESTAMPTZ,
    -- Timestamps.
    created_at                 TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    -- 24h TTL from creation. A housekeeping job may set stage='expired'
    -- for rows past this that are not already terminal.
    expires_at                 TIMESTAMPTZ   NOT NULL,
    -- Callback bookkeeping.
    callback_sent_at           TIMESTAMPTZ,
    callback_failed_at         TIMESTAMPTZ,
    callback_error             TEXT,
    CONSTRAINT signatures_stage_check
        CHECK (stage IN (
            'created',   -- ceremony opened, nothing uploaded yet
            'identity',  -- >=1 evidence uploaded or validated
            'consent',   -- all 4 evidences validated, waiting explicit consent
            'otp',       -- consent given, OTP requested
            'signing',   -- OTP verified, `sign` lambda dispatched
            'signed',    -- successful terminal state
            'expired',   -- reached expires_at before signed
            'failed'     -- `sign` lambda raised
        ))
);

-- Housekeeping index: only scans ceremonies that could still be expired.
CREATE INDEX signatures_expires_idx ON signatures (expires_at)
    WHERE stage NOT IN ('signed', 'expired', 'failed');

-- Signer-side lookups (audit or listing by email).
CREATE INDEX signatures_signer_email_idx ON signatures (signer_email, created_at DESC);

-- Give `processes` a nullable pointer to its ceremony's sign_id. This
-- replaces the previous `signatures.process_id` FK and lets `processes`
-- fetch its ceremony without signatures needing to know about it. It's
-- nullable because processes can be in earlier stages (form, documents)
-- without a ceremony yet.
ALTER TABLE processes ADD COLUMN sign_id VARCHAR(64);

-- +migrate down

DROP INDEX IF EXISTS signatures_signer_email_idx;
DROP INDEX IF EXISTS signatures_expires_idx;
DROP TABLE IF EXISTS signatures;
ALTER TABLE processes DROP COLUMN IF EXISTS sign_id;

-- Best-effort restore of the old v1 shape so the rollback leaves a
-- working `signatures` table for the previous handler code. Data is not
-- recovered (dropped rows are gone).
CREATE TABLE signatures (
    id               UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    process_id       UUID          NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    token            VARCHAR(64)   NOT NULL UNIQUE,
    email            VARCHAR(320)  NOT NULL,
    stage            VARCHAR(20)   NOT NULL DEFAULT 'review',
    pdf_key          TEXT          NOT NULL,
    page             INT           NOT NULL DEFAULT 1,
    pos_x            NUMERIC(5,2)  NOT NULL,
    pos_y            NUMERIC(5,2)  NOT NULL,
    cedula_front_key TEXT,
    cedula_back_key  TEXT,
    face_key         TEXT,
    signature_key    TEXT,
    signed_pdf_key   TEXT,
    otp_hash         VARCHAR(64),
    otp_expires_at   TIMESTAMPTZ,
    otp_attempts     INT           NOT NULL DEFAULT 0,
    doc_hash         VARCHAR(64),
    signed_at        TIMESTAMPTZ,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT signatures_stage_check
        CHECK (stage IN ('review', 'identity', 'drawing', 'otp', 'signed'))
);

CREATE INDEX signatures_process_id_idx ON signatures (process_id, created_at DESC);
