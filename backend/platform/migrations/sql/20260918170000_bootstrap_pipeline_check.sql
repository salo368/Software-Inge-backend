-- Migracion de bootstrap.
--
-- Crea una tabla testigo pequenita para validar end-to-end que el pipeline
-- de migrations funciona: la Lambda cdts-<stage>-migrations-apply se
-- desplego, se invoco desde el workflow, alcanzo la BD via SSM, corrio
-- SET LOCAL search_path al schema del stage, creo la tabla y registro la
-- version en schema_migrations.
--
-- No se usa en runtime; puede borrarse mas adelante con una migracion
-- posterior cuando ya tengamos servicios reales corriendo.

-- +migrate up
CREATE TABLE IF NOT EXISTS _pipeline_check (
  id          SERIAL PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  schema_seen TEXT        NOT NULL DEFAULT current_schema()
);

INSERT INTO _pipeline_check DEFAULT VALUES;

-- +migrate down
DROP TABLE IF EXISTS _pipeline_check;
