# data/

Datos estáticos **compartidos por más de un servicio**: semillas, catálogos, fixtures
globales, mocks de referencia. Nada mutable en runtime; para eso está la BD.

Ejemplos válidos:

- `data/seed/countries.csv` — catálogo global de países.
- `data/seed/document-types.json` — tipos de documento aceptados en todo el sistema.
- `data/fixtures/sample-signature.json` — fixture usado por tests de varios servicios.

Ejemplos NO válidos (irían en `services/<service>/data/`):

- `data/signature/schemas/request.json` — es del dominio `signature`.

Si un servicio necesita cargar esto en runtime, lo publica via `layers/shared/`.
Ver [`docs/repo-structure.md`](../docs/repo-structure.md) §7.
