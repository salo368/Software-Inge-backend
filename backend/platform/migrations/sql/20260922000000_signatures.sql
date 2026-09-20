-- Digital signature ceremony for a process sitting in the `signature` stage.
-- One row per ceremony, addressed by an unguessable token so the signer can
-- open it from any device without a session. The row doubles as the audit
-- trail: identity evidence keys, the OTP challenge and the SHA-256 of the
-- final document all live here.

-- +migrate up

CREATE TABLE signatures (
    id               UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    process_id       UUID          NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    token            VARCHAR(64)   NOT NULL UNIQUE,
    email            VARCHAR(320)  NOT NULL,
    stage            VARCHAR(20)   NOT NULL DEFAULT 'review',
    -- Unsigned investment order and where the drawn signature gets stamped,
    -- as a percentage of the page measured from the top-left corner.
    pdf_key          TEXT          NOT NULL,
    page             INT           NOT NULL DEFAULT 1,
    pos_x            NUMERIC(5,2)  NOT NULL,
    pos_y            NUMERIC(5,2)  NOT NULL,
    -- Identity evidence, uploaded straight to S3 with presigned URLs
    cedula_front_key TEXT,
    cedula_back_key  TEXT,
    face_key         TEXT,
    signature_key    TEXT,
    signed_pdf_key   TEXT,
    -- OTP challenge that seals the ceremony
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

-- +migrate down

DROP TABLE IF EXISTS signatures;
