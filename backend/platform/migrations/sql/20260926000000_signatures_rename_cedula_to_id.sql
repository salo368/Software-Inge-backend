-- Renames the cedula_* evidence columns to id_* so the signatures
-- service stays country-agnostic. The signature service is meant to be
-- reusable for any PDF signing flow, not just Colombian CDT, and
-- "cedula" hardcodes a Colombian document name into the schema.
--
-- No data is dropped: this is a pure RENAME COLUMN pair per side of the
-- identity document. The migration is safe to apply on dev even if
-- ceremonies exist -- SQL rename is atomic and preserves the values.
--
-- Paired changes:
--   * libs/orm/signatures.py             (column names, EVIDENCE_TYPES)
--   * services/signatures/utils/evidence.py (_PROBE_MAP)
--   * services/signatures/src/handlers/upload_url/handler.py (_EVIDENCE_MAP)
--   * S3 key layout: transactions/{sign_id}/cedula/* -> transactions/{sign_id}/id/*
--     (nothing to migrate because dev has no committed ceremonies yet;
--      any dangling S3 objects under cedula/* are orphans and will
--      lifecycle-expire in 30 days.)

-- +migrate up

ALTER TABLE signatures RENAME COLUMN cedula_front_key           TO id_front_key;
ALTER TABLE signatures RENAME COLUMN cedula_back_key            TO id_back_key;
ALTER TABLE signatures RENAME COLUMN cedula_front_validated_at  TO id_front_validated_at;
ALTER TABLE signatures RENAME COLUMN cedula_back_validated_at   TO id_back_validated_at;

-- +migrate down

ALTER TABLE signatures RENAME COLUMN id_front_key           TO cedula_front_key;
ALTER TABLE signatures RENAME COLUMN id_back_key            TO cedula_back_key;
ALTER TABLE signatures RENAME COLUMN id_front_validated_at  TO cedula_front_validated_at;
ALTER TABLE signatures RENAME COLUMN id_back_validated_at   TO cedula_back_validated_at;
