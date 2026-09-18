# platform/migrations — bloque de despliegue de infraestructura

Bloque de **infraestructura runtime** (§5.2 de `docs/repo-structure.md`) que
aplica las **migraciones de esquema de PostgreSQL** a la BD compartida del
proyecto. Es un bloque de despliegue propio, hermano de los demas bloques en
`backend/platform/` y de los servicios de negocio en `backend/services/`.

Ver [`docs/repo-structure.md`](../../../docs/repo-structure.md) §14 "Bloques
de despliegue".

## Como funciona

Cada migracion es **un archivo `.sql`** dentro de [`sql/`](./sql/), con nombre:

```
YYYYMMDDHHMMSS_snake_case_descripcion.sql
```

Ejemplo: `20260918153000_create_users_table.sql`.

El nombre determina el **orden de ejecucion** (lexicografico == cronologico).

Cada `.sql` tiene dos secciones separadas por comentarios sentinel:

```sql
-- +migrate up
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL UNIQUE
);

-- +migrate down
DROP TABLE users;
```

- `up` es obligatorio.
- `down` es opcional pero recomendado (permite rollback manual).

El estado se guarda en la tabla **`schema_migrations`** (creada la primera vez
por la misma Lambda) con columnas `(version TEXT PRIMARY KEY, applied_at
TIMESTAMPTZ NOT NULL DEFAULT now())`. `version` = nombre del archivo sin `.sql`.

## Convencion de schema (IMPORTANTE)

**Nunca calificar el schema en un `.sql`**. No escribas `dev.users`,
`pro.users`, ni `public.users`. Escribi siempre el nombre pelado:

```sql
-- CORRECTO
CREATE TABLE users (id UUID PRIMARY KEY);
CREATE INDEX users_email_idx ON users (email);
ALTER TABLE users ADD COLUMN nickname TEXT;

-- INCORRECTO (el linter falla el PR)
CREATE TABLE dev.users (id UUID PRIMARY KEY);
CREATE TABLE pro.orders (id UUID PRIMARY KEY);
CREATE INDEX pro.users_email_idx ON pro.users (email);
```

### Por que?

El **mismo archivo `.sql`** se aplica a los dos ambientes en dos runs distintos:

- Deploy DEV -> invoca `cdts-dev-migrations-apply` -> `SET LOCAL search_path
  TO dev` -> tu `CREATE TABLE users` crea `dev.users`.
- Deploy PRO -> invoca `cdts-pro-migrations-apply` -> `SET LOCAL search_path
  TO pro` -> el **mismo** archivo crea `pro.users`.

Si el `.sql` dice `CREATE TABLE dev.users`, entonces en el deploy PRO **se
crearia `dev.users`** en produccion (schema equivocado), silenciosamente.

### Otras cosas que el linter prohibe

Tambien esta prohibido y falla el CI:

- `SET search_path TO ...` dentro de un `.sql`. Es responsabilidad exclusiva
  de la Lambda; si un `.sql` lo hace, contamina la migracion siguiente.
- `CREATE SCHEMA` / `DROP SCHEMA`. Los schemas `dev` y `pro` se crean **fuera
  del pipeline** (una sola vez, manualmente al bootstrap de la BD). Ninguna
  migracion debe crearlos ni borrarlos.
- Nombres de archivo que no matcheen `YYYYMMDDHHMMSS_snake_case.sql`.
- Archivos sin la seccion `-- +migrate up`.

El linter vive en [`scripts/ci/lint-migrations.py`](../../../scripts/ci/lint-migrations.py)
y corre como job `Lint migrations` en cada PR. Es sencillo pero suficiente:
strippea strings literales y comentarios antes de matchear, asi que un
comentario `-- este cambio afecta dev.users` o un string literal
`'hola dev@ejemplo'` no dispara falso positivo.

### Referenciar el otro schema (raro)

Si alguna vez necesitas referenciar el schema del otro ambiente (ej. un query
de mantenimiento que compara `pro.users` con `dev.users`), eso **no es una
migracion**, es un query manual — sacalo del pipeline.

## Runtime (ya implementado)

- **Lambda**: `cdts-<stage>-migrations-apply` (runtime `python3.11`, memoria
  512 MB, timeout 300 s, fuera de VPC).
- **Driver**: [`pg8000`](https://pypi.org/project/pg8000/) — puro Python, se
  empaqueta directo en el bundle sin binarios ni layers.
- **Credenciales**: la Lambda lee `/cdts/<stage>/db/{host,port,name,user,
  password,schema}` de SSM (con `WithDecryption=True` para el password) al
  arrancar.
- **Trigger**: sin eventos declarados. El pipeline invoca sincronicamente con
  `aws lambda invoke` tras el `serverless-compose deploy migrations`.
- **Idempotencia**: cada archivo se aplica en su propia transaccion con
  `SET LOCAL search_path TO <stage>`. Si ya esta en `schema_migrations`, se
  saltea. Si falla uno, se aborta el batch (no continua con los siguientes)
  y el pipeline marca el deploy como fallido.

### Como agregar una migracion

1. Crea `backend/platform/migrations/sql/YYYYMMDDHHMMSS_snake_case_desc.sql`
   con las secciones `-- +migrate up` y opcionalmente `-- +migrate down`.
2. Abri PR contra `develop`. El linter valida convencion y CI corre.
3. Al mergear, `Deploy DEV` invoca la Lambda -> aplica la migracion sobre
   schema `dev`.
4. Cuando este validado en dev, abri PR de la MISMA rama contra `main`. Al
   mergear, `Deploy PRO` la aplica sobre schema `pro`.

### Rerun manual

```bash
# desde local con credenciales validas del deployer o admin:
aws lambda invoke \
  --function-name cdts-dev-migrations-apply \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/response.json
cat /tmp/response.json
```

O desde GitHub Actions: `Deploy DEV` (o `Deploy PRO`) -> "Run workflow" ->
input `block=migrations`.

## Orden respecto a otros bloques

`migrations` **siempre se despliega primero** cuando forma parte del plan. Ver
`scripts/ci/plan-deploy.sh`. Motivo: los servicios que llegan despues asumen
que el esquema ya esta al dia.

## Reglas duras

1. **Nunca editar un `.sql` ya mergeado a `main`**. Si algo salio mal, escribir
   una migracion nueva con timestamp posterior que corrija.
2. **Nunca renombrar** un archivo ya aplicado en algun ambiente. Se rompe el
   trackeo por nombre.
3. **Cada archivo es idempotente donde sea posible** (`CREATE TABLE IF NOT
   EXISTS`, `ALTER TABLE ... IF NOT EXISTS`) para poder re-aplicar sin fallos
   si algo se aborta a la mitad.
4. **No mezclar DDL y DML pesado en el mismo archivo** si el DML puede tardar
   varios minutos: separar en dos migraciones consecutivas.
5. **No dependencias entre servicios y migraciones sin declararlas**: los
   `serverless.yml` de los servicios usan `dependsOn: [migrations]` cuando
   necesitan una version minima de esquema.
