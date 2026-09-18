# utils/

Utilidades **genéricas cross-domain**. Código Python sin lógica de negocio de ningún
dominio específico. Es la **fuente** que alimenta el layer `layers/shared/` para que
las Lambdas puedan importarlas en runtime.

Ejemplos válidos:

- `utils/formatting.py` — formateo de fechas, montos, etc.
- `utils/http/responses.py` — helpers de responses estándar (`json_response(200, body)`).
- `utils/logging/context.py` — logger estructurado con request-id automático.
- `utils/aws/ssm.py` — wrapper cacheado sobre SSM Parameter Store.

Ejemplos NO válidos (irían en `services/<service>/utils/`):

- `utils/signature_ocr.py` — es del dominio `signature`.
- `utils/access_tokens.py` — es del dominio `access`.

Reglas:

- Sin imports desde ningún `services/*`.
- Sin lógica de negocio; solo primitives reutilizables.
- Cada módulo con su docstring explicando qué expone.

Ver [`docs/repo-structure.md`](../docs/repo-structure.md) §7.
