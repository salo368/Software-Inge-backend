# Estructura del repositorio CDTS

Reglas obligatorias de organización del código. Aplica tanto a humanos como a la IA
(Cursor / Claude / etc.). Si algo no encaja en estas reglas, hablarlo antes de romperlas.

---

## 1. Todo es Serverless

Todo el backend corre en **AWS Lambda + API Gateway HTTP API**, orquestado con
**Serverless Framework v3**. No hay contenedores, no hay EC2, no hay servidores
tradicionales.

## 2. Stages

Solo existen dos stages en todo el proyecto:

- `dev` — sandbox, deploy automático al mergear PR a `develop`.
- `pro` — producción, deploy automático al mergear PR a `main`.

**No usar** `prod`, `staging`, `qa`, `test`, ni ningún otro. Solo `dev` y `pro`.

## 3. Naming de recursos AWS

Toda función Lambda y todo recurso que la acompañe se nombra así:

```
cdts-<stage>-<service>-<function>
```

Reglas:

- `<stage>`: `dev` o `pro`. Una sola palabra.
- `<service>`: nombre del dominio. **Idealmente una sola palabra** (`access`, `signature`,
  `payments`). Si no se puede, usar `kebab-case` pero justificarlo.
- `<function>`: nombre de la Lambda. **Este es el único que puede tener múltiples
  palabras** separadas por guión (`create-signature`, `refresh-token`).

Ejemplos válidos:

| Lambda | Nombre AWS |
|---|---|
| Login del servicio access | `cdts-dev-access-login` |
| Crear firma en signature | `cdts-pro-signature-create-signature` |
| Refrescar token de access | `cdts-dev-access-refresh-token` |

## 4. Un servicio = un dominio de negocio

Cada carpeta bajo `services/` es un **servicio** y representa **un solo dominio**
(bounded context). Ejemplos: `access`, `signature`, `payments`.

- Un servicio nunca importa código de otro servicio directamente.
- Lo compartido va en `layers/shared/` (una Lambda Layer publicada por su propio
  micro-serverless).
- Cada servicio se registra en el `serverless-compose.yml` de la raíz.

## 5. Estructura obligatoria de un servicio

```
services/<service>/
├── serverless.yml          ← definición del servicio (provider, plugins, functions)
├── utils/                  ← helpers PRIVADOS del dominio (no exportar afuera)
├── data/                   ← modelos, DTOs, JSON schemas, seed/static data
└── src/
    ├── handlers/           ← API Lambdas (HTTP via API Gateway)
    │   └── <function>/
    │       ├── handler.py
    │       └── function.yml
    ├── scheduled/          ← Lambdas por schedule (EventBridge cron/rate)
    │   └── <function>/
    │       ├── handler.py
    │       └── function.yml
    └── workers/            ← Worker Lambdas (SQS / SNS / Streams / async invoke)
        └── <function>/
            ├── handler.py
            └── function.yml
```

### Reglas de las tres subcarpetas de `src/`

| Carpeta | Trigger | Ejemplo |
|---|---|---|
| `handlers/` | API Gateway HTTP API | `POST /signature` → `services/signature/src/handlers/create-signature/handler.py` |
| `scheduled/` | EventBridge `schedule` (rate/cron) | Job diario que limpia OTPs expirados |
| `workers/` | SQS, SNS, DynamoDB Streams, invoke async | Procesa un item de cola de firmas pendientes |

**Nunca** poner un handler HTTP dentro de `workers/`, ni un cron dentro de `handlers/`.
El nombre de la subcarpeta identifica su naturaleza y su trigger.

## 6. Cada Lambda vive en su propia carpeta

Dentro de `handlers/`, `scheduled/` o `workers/`, cada Lambda es **una carpeta con
exactamente dos archivos**:

- `handler.py` — código Python (define la función `handler(event, context)`).
- `function.yml` — configuración Serverless de esa función (handler path, events,
  timeout, memory, iam, environment, etc.). Se referencia desde `serverless.yml`
  con `${file(./src/<tipo>/<function>/function.yml)}`.

Si una Lambda necesita más de un archivo (por tamaño o separación de concerns),
esos archivos van dentro de la misma carpeta de la Lambda, no fuera. Nada de
`src/handlers/utils_login.py`; si es helper compartido va en `services/<service>/utils/`.

## 7. Directorios a nivel raíz

Además de los servicios, la raíz del repo tiene 3 directorios de propósito general
para código y datos **compartidos por más de un servicio o por herramientas del repo**:

| Dir raíz | Propósito | Ejemplos |
|---|---|---|
| `config/` | Configuración estática cross-project (perfiles, feature flags globales, mapping de stages, listas de tipos permitidos, etc.) | `config/mime-types.json`, `config/countries.yml` |
| `utils/` | Utilidades genéricas cross-domain (sin lógica de negocio de ningún dominio específico) | `utils/formatting.py`, `utils/http/responses.py` |
| `data/` | Datos estáticos, semillas, fixtures globales, catálogos, mocks de referencia | `data/seed/countries.csv`, `data/fixtures/sample-signature.json` |

Reglas:

- Si algo es **usado por un solo servicio**, va dentro de `services/<service>/utils/`,
  `services/<service>/data/` o `services/<service>/config/` (si aplica), NO en la raíz.
- Si algo es **usado por >1 servicio**, entonces sí va en la raíz, pero **debe
  publicarse via `layers/shared/`** para que las Lambdas lo puedan importar.
  La carpeta raíz es la fuente; el layer es el vehículo de distribución.
- Nada de lógica de negocio en `config/` o `data/`. Solo declarativos.

## 8. Composición: `serverless-compose.yml`

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

## 9. Ejemplo completo mínimo

Estructura de un servicio `signature` con una Lambda HTTP `create-signature`,
un worker `sign` y un scheduled `cleanup-expired-otps`:

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
    │   └── create-signature/
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
  # Fuerza que las funciones se llamen cdts-<stage>-<service>-<function>
  # en vez del default de Serverless (<service>-<stage>-<function>).
  naming:
    functionName: cdts-${self:provider.stage}-signature-${self:function.name}

functions:
  create-signature:      ${file(./src/handlers/create-signature/function.yml)}
  sign:                  ${file(./src/workers/sign/function.yml)}
  cleanup-expired-otps:  ${file(./src/scheduled/cleanup-expired-otps/function.yml)}
```

`services/signature/src/handlers/create-signature/function.yml`:

```yaml
handler: src/handlers/create-signature/handler.handler
events:
  - httpApi:
      method: POST
      path: /signatures
environment:
  SIGNATURES_TABLE: !Ref SignaturesTable
```

`services/signature/src/handlers/create-signature/handler.py`:

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

## 10. Base de datos (PostgreSQL)

- Instancia única compartida entre stages: `cdts-dev` (nombre histórico).
- Dos schemas: `dev` y `pro`. **No usar `public`** (queda dropeado a propósito).
- `search_path` por default de la base: `pro, dev`. En prod las Lambdas ven `pro` sin
  calificar; en dev el código explícita `SET search_path TO dev` al abrir la conexión.
- Credenciales viven en SSM Parameter Store bajo `/cdts/<stage>/db/`:
  - `/cdts/<stage>/db/host`, `port`, `name`, `user`, `password`, `schema`.
- Nada de credenciales en el código ni en variables de entorno de Lambda; siempre
  via SSM.

## 11. Anti-patrones (rechazar en review)

- Carpetas `common/`, `shared/` o `helpers/` dentro de `src/`. Si es del dominio,
  va en `services/<service>/utils/`. Si es cross-domain, va en `layers/shared/`
  (fuente en la raíz `utils/`).
- Una Lambda cuyo `handler.py` importa código de otro servicio hermano.
- Mezclar tipos: un cron en `handlers/`, un HTTP en `workers/`, etc.
- Un `function.yml` que defina handler fuera de su propia carpeta.
- Múltiples Lambdas dentro de una misma carpeta (una carpeta = una Lambda).
- Código de negocio en la raíz del servicio (por fuera de `src/`, `utils/`, `data/`).
- Nombres de Lambda como `cdts-<service>-<stage>-<function>` (formato viejo del MVP).
  El orden correcto es `cdts-<stage>-<service>-<function>`.
- Uso de `prod` en cualquier archivo, YAML, script o doc. El nombre del stage
  productivo es `pro`.

## 12. Tests

Los tests viven en `tests/` en la raíz del repo, espejando la estructura:

```
tests/
├── test_access_login.py
├── test_signature_create_signature.py
└── ...
```

Cada test es del tipo pytest (`test_*.py`, funciones `test_*`). El CI corre
`pytest tests -ra` en cada PR.
