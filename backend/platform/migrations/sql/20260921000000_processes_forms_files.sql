-- Processes (CDT open flow) + user profile forms + uploaded files.
-- One process = one CDT being opened. Forms is a single upsertable record
-- per user (KYC + financial profile) that gets snapshotted into the process
-- once the user finishes the form stage. Files are S3 objects owned by a
-- process, registered by a Lambda triggered on S3 ObjectCreated.

-- +migrate up

CREATE TABLE forms (
    user_id           UUID          PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    -- KYC
    full_name         VARCHAR(200)  NOT NULL,
    birth_date        DATE          NOT NULL,
    document_type     VARCHAR(20)   NOT NULL,
    document_number   VARCHAR(30)   NOT NULL,
    phone             VARCHAR(30)   NOT NULL,
    address           VARCHAR(300)  NOT NULL,
    city              VARCHAR(120)  NOT NULL,
    -- Financial profile
    occupation        VARCHAR(120)  NOT NULL,
    economic_activity VARCHAR(120)  NOT NULL,
    monthly_income    NUMERIC(15,2) NOT NULL,
    monthly_expenses  NUMERIC(15,2) NOT NULL,
    total_assets      NUMERIC(15,2) NOT NULL,
    total_liabilities NUMERIC(15,2) NOT NULL,
    source_of_funds   VARCHAR(200)  NOT NULL,
    is_peps           BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE processes (
    id             UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bank_id        INT           NOT NULL REFERENCES banks(id),
    amount         NUMERIC(15,2) NOT NULL,
    term_days      INT           NOT NULL,
    rate           NUMERIC(5,2)  NOT NULL,
    stage          VARCHAR(20)   NOT NULL DEFAULT 'form',
    form_snapshot  JSONB,
    signed_at      TIMESTAMPTZ,
    paid_at        TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT processes_stage_check
        CHECK (stage IN ('form', 'documents', 'signature', 'payment', 'done'))
);

CREATE INDEX processes_user_id_idx ON processes (user_id, created_at DESC);

CREATE TABLE files (
    id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    process_id    UUID          NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    file_type     VARCHAR(50)   NOT NULL,
    s3_key        TEXT          NOT NULL UNIQUE,
    original_name VARCHAR(300),
    size_bytes    BIGINT,
    content_type  VARCHAR(100),
    uploaded_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX files_process_id_idx ON files (process_id);

-- +migrate down

DROP TABLE IF EXISTS files;
DROP TABLE IF EXISTS processes;
DROP TABLE IF EXISTS forms;
