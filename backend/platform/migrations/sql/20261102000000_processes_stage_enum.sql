-- processes.stage becomes a native Postgres enum (process_stage) instead of
-- a free-form VARCHAR + CHECK constraint. Also grows the stage list: two
-- stages are inserted between `payment` and the terminal stage -- `review`
-- (ops checks the signed + paid file before handing it to the bank) and
-- `sent_to_bank` (handed off, waiting on the bank's own confirmation) -- and
-- the old terminal stage `done` is renamed to `completed`. Values are
-- uppercased to read as enum labels rather than free text.
--
-- Paired changes: libs/orm/processes.py (STAGES, default, advance_to()).

-- +migrate up

CREATE TYPE process_stage AS ENUM (
    'FORM', 'DOCUMENTS', 'SIGNATURE', 'PAYMENT', 'REVIEW', 'SENT_TO_BANK', 'COMPLETED'
);

ALTER TABLE processes
    ALTER COLUMN stage DROP DEFAULT;

ALTER TABLE processes
    DROP CONSTRAINT IF EXISTS processes_stage_check;

ALTER TABLE processes
    ALTER COLUMN stage TYPE process_stage
    USING (
        CASE stage
            WHEN 'form' THEN 'FORM'
            WHEN 'documents' THEN 'DOCUMENTS'
            WHEN 'signature' THEN 'SIGNATURE'
            WHEN 'payment' THEN 'PAYMENT'
            WHEN 'done' THEN 'COMPLETED'
            ELSE UPPER(stage)
        END
    )::process_stage;

ALTER TABLE processes
    ALTER COLUMN stage SET DEFAULT 'FORM'::process_stage;

-- +migrate down

-- Best-effort: rows already moved into the two new stages (`REVIEW`,
-- `SENT_TO_BANK`) have no pre-enum equivalent, so they fall back to
-- `documents` rather than failing the rollback outright.
ALTER TABLE processes
    ALTER COLUMN stage DROP DEFAULT;

ALTER TABLE processes
    ALTER COLUMN stage TYPE VARCHAR(20)
    USING (
        CASE stage::text
            WHEN 'FORM' THEN 'form'
            WHEN 'DOCUMENTS' THEN 'documents'
            WHEN 'SIGNATURE' THEN 'signature'
            WHEN 'PAYMENT' THEN 'payment'
            WHEN 'COMPLETED' THEN 'done'
            ELSE 'documents'
        END
    );

ALTER TABLE processes
    ALTER COLUMN stage SET DEFAULT 'form';

ALTER TABLE processes
    ADD CONSTRAINT processes_stage_check
        CHECK (stage IN ('form', 'documents', 'signature', 'payment', 'done'));

DROP TYPE process_stage;
