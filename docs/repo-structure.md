# Estructura del repositorio CDTS

Reglas obligatorias de organización del código. Aplica tanto a humanos como a la IA
(Cursor / Claude / etc.). Si algo no encaja en estas reglas, hablarlo antes de romperlas.

---

## 1. Todo es Serverless

Todo el backend corre en **AWS Lambda + API Gateway HTTP API**, orquestado con
**Serverless Framework v3**. No hay contenedores, no hay EC2, no hay servidores
tradicionales.

## 2. Un servicio = un dominio de negocio

Cada carpeta bajo `services/` es un **servicio** y representa **un solo dominio**
(bounded context). Ejemplos: `access`, `signature`, `moc`, `cdts`.

- Un servicio nunca importa código de otro servicio directamente.
- Lo compartido va en `layers/shared/` (una Lambda Layer publicada por su propio
  micro-serverless).
- Cada servicio se registra en el `serverless-compose.yml` de la raíz.

## 3. Estructura obligatoria de un servicio

```
services/<domain>/
├── serverless.yml          ← definición del servicio (provider, plugins, functions)
├── utils/                  ← helpers PRIVADOS del dominio (no exportar afuera)
├── data/                   ← modelos, DTOs, JSON schemas, seed/static data
└── src/
    ├── handlers/           ← API Lambdas (HTTP via API Gateway)
    │   └── <lambda-name>/
    │       ├── handler.py
    │       └── function.yml
    ├── scheduled/          ← Lambdas por schedule (EventBridge cron/rate)
    │   └── <lambda-name>/
    │       ├── handler.py
    │       └── function.yml
    └── workers/            ← Worker Lambdas (SQS / SNS / Streams / async invoke)
        └── <lambda-name>/
            ├── handler.py
            └── function.yml
```

### Reglas de las tres subcarpetas de `src/`

| Carpeta | Trigger | Ejemplo |
|---|---|---|
| `handlers/` | API Gateway HTTP API | `POST /signature` → `services/signature/src/handlers/create/handler.py` |
| `scheduled/` | EventBridge `schedule` (rate/cron) | Job diario que limpia OTPs expirados |
| `workers/` | SQS, SNS, DynamoDB Streams, invoke async | Procesa un item de cola de firmas pendientes |

**Nunca** poner un handler HTTP dentro de `workers/`, ni un cron dentro de `handlers/`.
El nombre de la subcarpeta identifica su naturaleza y su trigger.

## 4. Cada Lambda vive en su propia carpeta

Dentro de `handlers/`, `scheduled/` o `workers/`, cada Lambda es **una carpeta con
exactamente dos archivos**:

- `handler.py` — código Python (define la función `handler(event, context)`).
- `function.yml` — configuración Serverless de esa función (handler path, events,
  timeout, memory, iam, environment, etc.). Se referencia desde `serverless.yml`
  con `${file(./src/<tipo>/<lambda-name>/function.yml)}`.

Si una Lambda necesita más de un archivo (por tamaño o separación de concerns),
esos archivos van dentro de la misma carpeta de la Lambda, no fuera. Nada de
`src/handlers/utils_login.py`; si es helper compartido va en `services/<domain>/utils/`.

## 5. Convenciones de nombres

| Elemento | Convención | Ejemplo |
|---|---|---|
| Servicio | `kebab-case` en la carpeta y en el `service:` del yml | `services/digital-signature/` → `service: cdts-digital-signature` |
| Carpeta de Lambda | `kebab-case` | `src/handlers/create-signature/` |
| Función en `function.yml` | `kebab-case` | `create-signature` |
| Recursos AWS creados por CFN | `cdts-<service>-<stage>-<resource>` | `cdts-signature-dev-signatures-table` |
| Roles IAM | mismo prefijo | `cdts-signature-dev-create-signature-role` |

## 6. Composición: `serverless-compose.yml`

Todos los servicios se declaran en el `serverless-compose.yml` de la raíz. El orden
de `dependsOn` importa (por ejemplo, todos dependen del `shared-layer`):

```yaml
services:
  shared-layer:
    path: layers/shared

  access:
    path: services/access
    dependsOn:
      - shared-layer

  signature:
    path: services/signature
    dependsOn:
      - shared-layer
      - access
```

## 7. Ejemplo completo mínimo

Estructura de un servicio `signature` con una Lambda HTTP `create`, un worker `sign`
y un scheduled `cleanup-expired-otps`:

```
services/signature/
├── serverless.yml
├── utils/
│   └── ocr.py
├── data/
│   └── schemas/
│       └── signature_request.json
└── src/
    ├── handlers/
    │   └── create/
    │       ├── handler.py
    │       └── function.yml
    ├── scheduled/
    │   └── cleanup-expired-otps/
    │       ├── handler.py
    │       └── function.yml
    └── workers/
        └── sign/
            ├── handler.py
            └── function.yml
```

`services/signature/serverless.yml`:

```yaml
service: cdts-signature

frameworkVersion: '3'

provider:
  name: aws
  runtime: python3.11
  region: ${opt:region, 'us-east-1'}
  stage: ${opt:stage, 'dev'}
  memorySize: 512
  timeout: 15

functions:
  create:           ${file(./src/handlers/create/function.yml)}
  sign:             ${file(./src/workers/sign/function.yml)}
  cleanup-expired-otps: ${file(./src/scheduled/cleanup-expired-otps/function.yml)}
```

`services/signature/src/handlers/create/function.yml`:

```yaml
handler: src/handlers/create/handler.handler
events:
  - httpApi:
      method: POST
      path: /signatures
environment:
  SIGNATURES_TABLE: !Ref SignaturesTable
```

`services/signature/src/handlers/create/handler.py`:

```python
import json

def handler(event, context):
    body = json.loads(event.get("body") or "{}")
    # ...logica...
    return {
        "statusCode": 201,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"id": "sig_123"}),
    }
```

## 8. Anti-patrones (rechazar en review)

- Carpetas `common/`, `shared/` o `helpers/` dentro de `src/`. Si es del dominio,
  va en `services/<domain>/utils/`. Si es cross-domain, va en `layers/shared/`.
- Una Lambda cuyo `handler.py` importa código de otro servicio hermano.
- Mezclar tipos: un cron en `handlers/`, un HTTP en `workers/`, etc.
- Un `function.yml` que defina handler fuera de su propia carpeta.
- Múltiples Lambdas dentro de una misma carpeta (una carpeta = una Lambda).
- Código de negocio en la raíz del servicio (por fuera de `src/`, `utils/` o `data/`).

## 9. Tests

Los tests viven en `tests/` en la raíz del repo, espejando la estructura:

```
tests/
├── test_access_login.py
├── test_signature_create.py
└── ...
```

Cada test es del tipo pytest (`test_*.py`, funciones `test_*`). El CI corre
`pytest tests -ra` en cada PR.
