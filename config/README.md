# config/

Configuración declarativa **compartida por más de un servicio o por herramientas del
repo**. Nada de lógica de negocio, solo YAML/JSON/TOML.

Ejemplos válidos:

- `config/mime-types.json` — mapping de content-types permitidos globalmente.
- `config/countries.yml` — catálogo de países ISO.
- `config/stage-limits.yml` — límites por stage compartidos por varias Lambdas.

Ejemplos NO válidos (irían en `services/<service>/`):

- `config/signature-otp-rules.yml` — es exclusivo del dominio `signature`. Va en
  `services/signature/config/otp-rules.yml`.

Si algo aquí es leído en runtime desde Lambda, publicarlo via `layers/shared/`.
Ver [`docs/repo-structure.md`](../docs/repo-structure.md) §7.
