-- Bootstrap: end-to-end smoke test for the migrations pipeline.

-- +migrate up
CREATE TABLE IF NOT EXISTS _pipeline_check (
  id          SERIAL PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  schema_seen TEXT        NOT NULL DEFAULT current_schema()
);

INSERT INTO _pipeline_check DEFAULT VALUES;

-- +migrate down
DROP TABLE IF EXISTS _pipeline_check;
