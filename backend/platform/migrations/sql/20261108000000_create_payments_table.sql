-- Payments of a CDT process (service `payments`). For now only the table:
-- the amount paid and the S3 key of the payment file.

-- +migrate up

CREATE TABLE IF NOT EXISTS payments (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    process_id  UUID          NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    amount      NUMERIC(15,2) NOT NULL,
    s3_file     TEXT
);

CREATE INDEX IF NOT EXISTS payments_process_id_idx ON payments (process_id);

-- +migrate down

DROP TABLE IF EXISTS payments;
