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

### 3.1 Naming interno (Python / filesystem) vs naming AWS

Python **no acepta guiones** en nombres de módulos ni de funciones. Por eso el
mismo concepto se escribe de dos formas distintas según el contexto:

| Cosa | Estilo | Ejemplo |
|---|---|---|
| Carpeta de la Lambda | `snake_case` **obligatorio** | `src/handlers/refresh_token/` |
| Archivo del handler | siempre `handler.py` | `handler.py` |
| Función entrypoint | siempre `def handler(event, context)` | — |
| Nombre AWS de la Lambda | `kebab-case`, **autogenerado** por el helper (§8.1) | `cdts-dev-auth-refresh-token` |
| Handler path | **autogenerado**: `src/<tipo>/<carpeta>/handler.handler` | — |

Regla mnemotécnica: **en la carpeta usás `_`; en el nombre AWS ese `_` se vuelve `-`**.

El dev **no escribe** el `name:` ni el `handler:` en `function.yml`; los deriva
el generador `backend/utils/build-functions.js` a partir de la convención (ver
§8.1). Si por alguna razón se necesita romper la convención, ambos campos son
override-ables declarándolos explícitos en el `function.yml` (escape hatch).

**No** usar `provider.naming.functionName` en el `serverless.yml` — esa
propiedad no existe en Serverless Framework 3 y falla con
`Cannot resolve variable at "provider.naming.functionName"`. En su lugar:

- `provider.stackName: cdts-${sls:stage}-<service>` — nombre del CFN stack.
- `functions: ${file(./functions.js):build}` — delega el registro completo al
  generador (auto-descubre Lambdas y arma `name` + `handler`).

### 3.2 API Gateway: `httpApi` (v2) por default

Los HTTP events se declaran con `- httpApi:` (API Gateway v2), no `- http:`
(v1). v2 es ~3.5× más barato, tiene CORS y JWT nativos, y usa payload v2 más
simple. v1 sólo se usa si necesitás WAF nativo o endpoints privados en VPC.

CORS se configura una sola vez a nivel provider, no por función:

```yaml
provider:
  httpApi:
    cors: true
```

## 4. Layout del repo

La raíz del repo agrupa **infraestructura de proyecto**; el runtime vive completo
bajo [`backend/`](../backend/).

```
repo/
├── .github/workflows/          ← CI/CD YAMLs
├── .cursor/rules/              ← reglas persistentes IA
├── docs/                       ← documentacion humana
├── scripts/ci/, scripts/iam/   ← CI helpers + IAM bootstrap
├── backend/                    ← ★ TODO el backend Serverless
│   ├── serverless-compose.yml
│   ├── package.json, package-lock.json
│   ├── requirements-dev.txt, pytest.ini
│   ├── .nvmrc, .python-version
│   ├── config/, utils/, data/    (§7)
│   ├── services/<service>/       (§5.1)
│   ├── platform/<name>/          (§5.2)
│   ├── layers/shared/            (Lambda Layer)
│   └── tests/
├── README.md, CONTRIBUTING.md
└── .gitignore
```

Todo el trabajo de Lambda, Serverless, dependencias Python/Node y tests unitarios
ocurre dentro de `backend/`. La raíz permanece "agnóstica".

La SPA que consume estas APIs **no vive en este repo**: está en
[`salo368/Software-Inge-frontend`](https://github.com/salo368/Software-Inge-frontend),
con su propio pipeline. Ver §5.4.

## 5. Servicios de dominio vs bloques de plataforma

El backend tiene dos tipos de bloques desplegables. Los dos se registran igual en
`backend/serverless-compose.yml`, tienen la misma estructura interna de código
Serverless, y son unidades de deploy independientes. Se separan **solo por
convención** para dejar clara la intención:

### 5.1 `backend/services/<name>/` — DOMINIO DE NEGOCIO

Cada carpeta bajo `backend/services/` es un **servicio** que representa **un solo
dominio** (bounded context). Servicios hoy vigentes:

| Servicio | Responsabilidad | Referencia |
|---|---|---|
| `auth` | Registro, login, refresh, `me`. Emite bearer tokens. | — |
| `banks` | Catálogo de bancos habilitados. | — |
| `files` | Presigned URLs para documentos genéricos del usuario. | — |
| `forms` | Snapshot del formulario que llena el usuario al abrir un CDT. | — |
| `processes` | Orquestador del wizard CDT (form → documents → signature → payment → done). | — |
| `signatures` | Servicio genérico de firma digital (agnóstico al dominio). | [`signatures-v2.md`](./signatures-v2.md) |

- Un servicio nunca importa código de otro servicio directamente. `processes`
  llama `signatures.create` por direct Lambda invoke, no por import.
- Lo compartido va en `backend/layers/shared/` (Lambda Layer publicada por su propio
  micro-serverless).
- Cross-service data va por presigned URL o por el patrón invoke sintético
  (`processes/utils/signature_bridge.py` es el ejemplo canónico).

### 5.2 `backend/platform/<name>/` — INFRAESTRUCTURA RUNTIME

Cada carpeta bajo `backend/platform/` es un **bloque de infra** con responsabilidad
técnica cross-dominio. Ejemplos:

- `platform/migrations/` — aplica el esquema SQL versionado a la BD.
- (futuros) `platform/observability/`, `platform/bootstrap/`, `platform/notifications/`.

Reglas:

- **No usar un servicio catch-all** `platform/infrastructure/` o similar. Cada
  responsabilidad tiene su propia carpeta descriptiva.
- Ningún bloque de `services/` puede importar código de `platform/`. Si hay algo
  reutilizable, va en `backend/layers/shared/`.
- Los bloques de `platform/` sí pueden ejecutar operaciones cross-dominio (ej.
  `migrations` toca schemas de todos), esa es su razón de existir.

### 5.3 Deploy es agnóstico al origen

Para el pipeline `services/` y `platform/` son iguales: cada carpeta directa es
un bloque descubierto automáticamente por `scripts/ci/plan-deploy.sh`. La única
regla especial: `migrations` se despliega **primero** si forma parte del plan
(ver §14).

### 5.4 El frontend vive en otro repo

La SPA está en
[`salo368/Software-Inge-frontend`](https://github.com/salo368/Software-Inge-frontend):
Angular 18 sobre S3 privado + CloudFront con OAC, stack `cdts-<stage>-frontend`,
con su propio pipeline y sus propias credenciales IAM (usuarios
`github-actions-<stage>-frontend-deployer`, que no pueden desplegar backend).

**No añadir un `frontend/` a este repo.** Se separó justamente para que backend y
cliente web se desplieguen y revisen de forma independiente.

El contrato entre los dos repos es deliberadamente delgado y va enteramente por AWS:

| Dirección | Mecanismo |
|---|---|
| Frontend → backend | Llama los HTTP API de cada servicio. Las URLs están hardcodeadas en los `environment.ts` de la SPA. |
| Backend → frontend | Lee el parámetro SSM `/cdts/<stage>/frontend/url`, que el stack del frontend publica al desplegarse, para armar enlaces absolutos hacia la SPA (el correo de la ceremonia de firma, por ejemplo). |

Se usa SSM y no un `Fn::ImportValue` a propósito: un import cruzado haría que
CloudFormation bloqueara cambios en el stack del frontend mientras el backend
dependa de él, y obligaría a un orden de despliegue entre repos. Leyendo el
parámetro en runtime, cada stack se despliega cuando quiera.

## 6. Estructura obligatoria de un bloque

Aplica a los dos tipos de bloque (`backend/services/<X>/` de negocio y
`backend/platform/<X>/` de infra), con la única diferencia de que los bloques
de `platform/` pueden tener carpetas adicionales propias de su responsabilidad
(por ejemplo, `platform/migrations/sql/`).

```
backend/{services,platform}/<name>/
├── serverless.yml          ← definición del servicio (provider, plugins, functions)
├── utils/                  ← helpers PRIVADOS del bloque (no exportar afuera)
├── data/                   ← modelos, DTOs, JSON schemas, seed/static data
└── src/
    ├── handlers/           ← API Lambdas (HTTP via API Gateway)
    │   └── <function>/
    │       ├── handler.py
    │       ├── function.yml
    │       └── test.py          ← pruebas unitarias colocalizadas (§13.1)
    ├── scheduled/          ← Lambdas por schedule (EventBridge cron/rate)
    │   └── <function>/
    │       ├── handler.py
    │       ├── function.yml
    │       └── test.py
    └── workers/            ← Worker Lambdas (SQS / SNS / Streams / async invoke)
        └── <function>/
            ├── handler.py
            ├── function.yml
            └── test.py
```

### Reglas de las tres subcarpetas de `src/`

| Carpeta | Trigger | Ejemplo |
|---|---|---|
| `handlers/` | API Gateway HTTP API | `POST /signature` → `backend/services/signature/src/handlers/create-signature/handler.py` |
| `scheduled/` | EventBridge `schedule` (rate/cron) | Job diario que limpia OTPs expirados |
| `workers/` | SQS, SNS, DynamoDB Streams, invoke async | Procesa un item de cola de firmas pendientes |

**Nunca** poner un handler HTTP dentro de `workers/`, ni un cron dentro de `handlers/`.
El nombre de la subcarpeta identifica su naturaleza y su trigger.

## 7. Directorios `backend/config/`, `backend/utils/`, `backend/data/`

Contenido **compartido por más de un servicio o por herramientas del backend**.

| Dir | Propósito | Ejemplos |
|---|---|---|
| `backend/config/` | Configuración declarativa cross-servicio | `mime-types.json`, `countries.yml` |
| `backend/utils/` | Utilidades genéricas cross-domain (fuente que alimenta a `backend/layers/shared/`) | `formatting.py`, `http/responses.py` |
| `backend/data/` | Datos estáticos, semillas, fixtures globales | `seed/countries.csv`, `fixtures/sample-signature.json` |

Reglas:

- Si algo es **usado por un solo servicio**, va dentro de `backend/services/<service>/`,
  NO en estas carpetas cross.
- Si algo es **usado por >1 servicio en runtime**, se publica via
  `backend/layers/shared/`. La carpeta `backend/utils/` es la fuente; el layer es
  el vehículo de distribución.
- Nada de lógica de negocio en `config/` o `data/`. Solo declarativos.

## 8. Cada Lambda vive en su propia carpeta

Dentro de `handlers/`, `scheduled/` o `workers/`, cada Lambda es **una carpeta con
exactamente tres archivos obligatorios**:

- `handler.py` — código Python (define la función `handler(event, context)`).
- `function.yml` — configuración **específica** de esa función (events, memory,
  timeout override, environment, layers, etc.). **NO lleva `name` ni `handler`**;
  ambos se autogeneran (§8.1).
- `test.py` — pruebas unitarias **colocalizadas** para esa Lambda (ver §13.1).
  Corren en el job `tests` del pipeline por bloque; si el `test.py` falla, el
  deploy del bloque no se ejecuta. `test.py` se excluye del zip via
  `package.patterns` en el `serverless.yml` de cada bloque.

Si una Lambda necesita más de un archivo, esos archivos van dentro de la misma carpeta
de la Lambda, no fuera.

### 8.1 Auto-registro de Lambdas (`functions.js`)

Cada bloque tiene un `functions.js` de 3 líneas que delega el registro al
generador compartido `backend/utils/build-functions.js`:

```js
// backend/{services,platform}/<block>/functions.js
'use strict';
module.exports.build = require('../../utils/build-functions')(__dirname);
```

Y en el `serverless.yml` del bloque:

```yaml
functions: ${file(./functions.js):build}
```

Al desplegar, el generador:

1. Escanea `src/{handlers,scheduled,workers}/*/function.yml`.
2. Valida que cada carpeta sea `snake_case` (falla el package si detecta un
   guión, mayúsculas u otro carácter).
3. Autoderiva por convención:
   - `name: cdts-<stage>-<service>-<folder-kebab>` (ej. carpeta `refresh_token/`
     con `service: auth` en `dev` → `cdts-dev-auth-refresh-token`).
   - `handler: src/<tipo>/<carpeta>/handler.handler`.
4. Hace merge con lo declarado en `function.yml` (events, timeout, memory,
   environment, layers, etc.). Los campos del `function.yml` **ganan** si
   declaran `name:` o `handler:` explícito (escape hatch para casos raros).

Ventajas: el dev sólo crea la carpeta con `handler.py` + `function.yml`, y la
Lambda aparece registrada con el nombre AWS correcto sin intervención. Cero
boilerplate, cero risk de typo en el prefix `cdts-<stage>-<service>-`.

Tests unitarios del generador en `backend/tests/build-functions.test.js`
(runner `node --test`, corre en el job `validate` de los deploys).

## 9. Composición: `backend/serverless-compose.yml`

Todos los servicios se declaran en `backend/serverless-compose.yml`. El orden de
`dependsOn` importa (por ejemplo, todos dependen del `shared-layer`):

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

Las rutas son **relativas a `backend/`**.

## 10. Ejemplo completo mínimo

Estructura de un servicio `signature` con una Lambda HTTP `create_signature`
(AWS: `cdts-<stage>-signature-create-signature`), un worker `sign` y un
scheduled `cleanup_expired_otps` (AWS: `cdts-<stage>-signature-cleanup-expired-otps`):

```
backend/services/signature/
├── serverless.yml
├── utils/
│   └── ocr.py
├── data/
│   └── schemas/
│       └── signature_request.json
└── src/
    ├── handlers/
    │   └── create_signature/       ← snake_case en la carpeta
    │       ├── handler.py
    │       └── function.yml
    ├── scheduled/
    │   └── cleanup_expired_otps/
    │       ├── handler.py
    │       └── function.yml
    └── workers/
        └── sign/
            ├── handler.py
            └── function.yml
```

`backend/services/signature/functions.js` (3 líneas, siempre igual):

```js
'use strict';
module.exports.build = require('../../utils/build-functions')(__dirname);
```

`backend/services/signature/serverless.yml`:

```yaml
service: signature

frameworkVersion: '3'

provider:
  name: aws
  runtime: python3.11
  region: ${opt:region, 'us-east-1'}
  stage: ${opt:stage, 'dev'}
  stackName: cdts-${sls:stage}-signature   # CFN stack
  memorySize: 512
  timeout: 15
  httpApi:
    cors: true                             # CORS global, no por funcion

# Auto-descubre y registra todas las Lambdas bajo
# src/{handlers,scheduled,workers}/* (ver §8.1).
functions: ${file(./functions.js):build}
```

`backend/services/signature/src/handlers/create_signature/function.yml`:

```yaml
# No lleva 'name' ni 'handler': el generador los autoderiva como
#   name:    cdts-<stage>-signature-create-signature
#   handler: src/handlers/create_signature/handler.handler
description: Crea una nueva solicitud de firma.
timeout: 40
events:
  - httpApi:
      method: POST
      path: /signatures
environment:
  SIGNATURES_TABLE: !Ref SignaturesTable
```

`backend/services/signature/src/handlers/create_signature/handler.py`:

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

## 11. Base de datos (PostgreSQL)

- Instancia única compartida entre stages: `cdts-dev` (nombre histórico).
- Dos schemas: `dev` y `pro`. **No usar `public`** (queda dropeado a propósito).
- `search_path` por default de la base: `pro, dev`. En prod las Lambdas ven `pro` sin
  calificar; en dev el código explícita `SET search_path TO dev` al abrir la conexión.
- Credenciales viven en SSM Parameter Store bajo `/cdts/<stage>/db/`:
  - `/cdts/<stage>/db/host`, `port`, `name`, `user`, `password`, `schema`.
- Nada de credenciales en el código ni en variables de entorno de Lambda; siempre
  via SSM.
- **Migraciones nunca califican schema**. Un `.sql` de
  `backend/platform/migrations/sql/` escribe `CREATE TABLE users`, no
  `CREATE TABLE dev.users`. La Lambda de migrations hace `SET LOCAL
  search_path TO <stage>` al inicio de cada transaccion y el mismo archivo se
  aplica en `dev` y `pro` sin cambios. El linter
  [`scripts/ci/lint-migrations.py`](../scripts/ci/lint-migrations.py) falla el
  CI si detecta un `dev.`, `pro.` o `public.` calificado, un `SET search_path`
  explicito, o `CREATE SCHEMA`/`DROP SCHEMA`. Ver
  [`backend/platform/migrations/README.md`](../backend/platform/migrations/README.md)
  para la convencion completa.

## 12. Anti-patrones (rechazar en review)

- Carpetas `common/`, `shared/` o `helpers/` dentro de `src/`. Si es del dominio,
  va en `backend/services/<service>/utils/`. Si es cross-domain, va en
  `backend/layers/shared/` (fuente en `backend/utils/`).
- Una Lambda cuyo `handler.py` importa código de otro servicio hermano.
- Mezclar tipos: un cron en `handlers/`, un HTTP en `workers/`, etc.
- Un `function.yml` que defina handler fuera de su propia carpeta.
- Múltiples Lambdas dentro de una misma carpeta (una carpeta = una Lambda).
- Código de negocio en la raíz del servicio (por fuera de `src/`, `utils/`, `data/`).
- Nombres de Lambda como `cdts-<service>-<stage>-<function>` (formato viejo del MVP).
  El orden correcto es `cdts-<stage>-<service>-<function>`.
- Uso de `prod` en cualquier archivo, YAML, script o doc. El nombre del stage
  productivo es `pro`.
- Carpeta de Lambda con guiones (`refresh-token/`, `create-signature/`). Va
  con `_` (`refresh_token/`, `create_signature/`); el guión aparece sólo en el
  nombre AWS declarado en `function.yml`.
- Uso de `provider.naming.functionName` en `serverless.yml`. Esa propiedad NO
  existe en Serverless Framework 3 y falla la resolución de variables. Usar
  `provider.stackName` para el CFN stack y `functions: ${file(./functions.js):build}`
  para el registro automático de Lambdas.
- Declarar `name:` o `handler:` en `function.yml` sin razón. Ambos se
  autogeneran por convención (§8.1); si aparecen, deben tener un comentario que
  justifique por qué se rompe la convención. Sin justificación, se rechaza en
  review.
- Uso de dots (`src.handlers.login.handler.handler`) en el `handler:` override.
  La convención es slashes: `src/handlers/login/handler.handler`.
- Enumerar Lambdas manualmente en el `functions:` del `serverless.yml`
  (`create_signature: ${file(./src/...)}`, una por línea). Es el trabajo del
  generador; si aparece, se refactoriza a `functions: ${file(./functions.js):build}`.
- `- http:` (API Gateway v1) por default. Usar `- httpApi:` (v2); v1 sólo si
  necesitás WAF o endpoints privados.
- CORS repetido dentro de cada `function.yml`. Va una sola vez en
  `provider.httpApi.cors`.
- Archivos del backend (Python, `serverless.yml`, `requirements-*.txt`, etc.) fuera
  de `backend/`. La raíz permanece para infra de proyecto.

## 13. Tests

Hay **dos ubicaciones** de tests, con propósitos distintos y ambas obligatorias:

### 13.1 Colocalizados: `test.py` al lado de cada `handler.py`

Cada Lambda **DEBE** tener un `test.py` en su propia carpeta (ver §8). Contrato:

- Es un archivo pytest normal, con al menos **tres casos** de piso (no techo):
  1. **Happy path** — evento válido → status esperado + payload esperado.
  2. **Validación de entrada** — evento con campos faltantes/inválidos → 400.
  3. **Falla de dominio** — dependencia que responde "no" (usuario no existe,
     token invalido, stage incorrecto, etc.) → status correcto y sin fuga de
     stack.
- **No** hace llamadas reales a AWS ni a la BD. Usa `monkeypatch` para
  reemplazar `Users.get_by_email`, `Processes.create`, `presign_upload`,
  `send_email`, etc. antes de invocar `handler(event, context)`.
- Importa el handler con la fixture `load_handler(__file__)` provista por
  [`backend/conftest.py`](../backend/conftest.py). Esa fixture carga el
  `handler.py` hermano bajo un nombre de módulo único para evitar colisiones
  cuando 20+ archivos se llaman igual.
- El `conftest.py` de `backend/` **stubbea `boto3` antes de que se importe
  cualquier handler**, para que `libs/core/db.py` (que llama a
  `boto3.client("ssm").get_parameters_by_path` en top-level) no explote al
  importar el módulo bajo prueba.

Plantilla mínima:

```python
# backend/services/auth/src/handlers/login/test.py
import json
from unittest.mock import MagicMock

def _event(body): return {"body": json.dumps(body)}

def test_login_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Users", MagicMock(
        get_by_email=MagicMock(return_value=MagicMock(password_hash="x", public_dict=lambda: {"id": "u"}))
    ))
    monkeypatch.setattr(h, "verify_password", MagicMock(return_value=True))
    monkeypatch.setattr(h, "issue_token", MagicMock(return_value=("tok", ...)))
    resp = h.handler(_event({"email": "a@b.co", "password": "x"}), None)
    assert resp["statusCode"] == 200
```

Estos `test.py` corren en el job `tests` del pipeline (§15), un shard por
bloque, en paralelo. Si el shard de un bloque rompe, **ninguno** se despliega
(`fail-fast: true`).

**Exclusión del zip**: el `serverless.yml` de cada bloque incluye
`- '!**/test.py'` y `- '!**/conftest.py'` en `package.patterns`. Sin eso, el
`test.py` se subiría a la Lambda y aumentaría el tamaño del zip para nada.

### 13.2 Cross-cutting: `backend/tests/`

Para tests que **no pertenecen a una Lambda específica** (parsers, helpers de
build, generadores compartidos):

```
backend/tests/
├── test_migrations_parser.py    ← unit test del parser SQL
├── build-functions.test.js       ← unit test del helper de auto-registro
├── integration_helpers.py        ← helpers para los integration.py (§13.3)
└── ...
```

Cada test es del tipo pytest (`test_*.py`, funciones `test_*`) o Node
(`*.test.js` via `node --test`). El CI corre `pytest tests -ra` **dentro de
`backend/`** en el job `validate` (una sola vez, no por bloque).

> `tests/integration_helpers.py` NO es un archivo de tests (no matchea
> `test_*.py`); es el módulo con los helpers compartidos que consumen los
> `integration.py` colocalizados. Ver §13.3.

### 13.3 Colocalizados en vivo: `integration.py` (opcional, solo dev)

Además del `test.py` "en seco" (unit, mockeado, bloquea deploy), cada
Lambda **PUEDE** tener un `integration.py` hermano que corre contra la
infra REAL de `dev` DESPUÉS del deploy. Sirve para dos cosas al mismo
tiempo:

1. **Contrato en vivo** — hace el request HTTP real contra API Gateway y
   verifica el status/shape que el frontend va a recibir.
2. **Validación de fuentes de reposo** — abre Postgres/S3 directamente y
   verifica que el efecto lateral persistió (fila del usuario existente,
   objeto en S3, token en `bearer_tokens`, worker async terminó, etc.).

Contrato:

- **Es opcional**. `test.py` sigue siendo obligatorio; `integration.py`
  se agrega donde tiene sentido (endpoints con efectos laterales
  persistentes o flujos async con workers). Handlers de solo lectura
  como `forms/get_mine` no lo necesitan.
- Cada test se marca con `@pytest.mark.integration` (o
  `pytestmark = pytest.mark.integration` a nivel de módulo).
- Un `pytest` local NO los ejecuta (se saltean via el hook
  `pytest_collection_modifyitems` en `backend/conftest.py`). Para
  correrlos explícitamente: `pytest --integration -m integration
  services/auth/src/handlers/register/`. Sin `--integration` aparecen
  como `SKIPPED`.
- Usan helpers de `backend/tests/integration_helpers.py`:
  `api_base(service)`, `db_conn()`, `query_one(sql, **params)`,
  `s3_head(bucket, key)`, `signup_and_login()`, `cleanup_user(email)`,
  `unique_email()`, `wait_for(condition)`.
- **Aislamiento**: cada test genera identificadores únicos con prefijo
  `itest-` (`unique_email()` → `itest-<uuid>@itest.cdts.dev`). Los
  `cleanup_*` en `finally` borran las filas creadas por el test. Los
  helpers de cleanup rechazan borrar cualquier cosa que no empiece con
  `itest-` como red de seguridad.
- **Descubrimiento del API URL**: `api_base(service)` primero busca el
  output `HttpApiUrl` del stack `cdts-dev-<service>` en CloudFormation
  y, si no está, hace fallback a `apigatewayv2 get-apis` filtrando por
  nombre. Cero configuración manual.

Plantilla mínima:

```python
# backend/services/auth/src/handlers/register/integration.py
import pytest, requests
from tests.integration_helpers import (
    api_base, cleanup_user, query_one, unique_email,
)

pytestmark = pytest.mark.integration


def test_register_persists_user_in_db():
    email = unique_email()
    try:
        r = requests.post(f"{api_base('auth')}/auth/register", json={
            "email": email, "password": "hunter22aa", "full_name": "Bot",
        }, timeout=15)
        assert r.status_code == 201

        # fuente de reposo: la fila realmente existe en Postgres.
        row = query_one("SELECT id, email, password_hash FROM users WHERE email = :e", e=email)
        assert row is not None
        assert row["password_hash"].startswith("$2")  # bcrypt marker
    finally:
        cleanup_user(email)  # ¡siempre!
```

Estos `integration.py` corren **dentro del "package" de su bloque** en
el pipeline (§15), **solo en Deploy DEV**. Un package es una llamada al
reusable workflow `.github/workflows/block-package.yml` que ejecuta en
orden `test → deploy → integration`. Es decir:

- El job `integration` tiene `continue-on-error: true` y `needs:
  [deploy]` dentro del mismo package.
- Un fallo NO revierte AWS: el deploy ya sucedió.
- El workflow termina en verde con warnings; los detalles quedan en
  annotations y en el artifact `pytest-integration-dev-<block>`.
- El resumen final (`summary`) muestra por bloque el estado
  (:white_check_mark: / :fast_forward: skipped / :x:), leyéndolo desde
  el artifact `integration-status-<block>` que cada package sube.
- Deploy PRO **no** corre integration (no queremos usuarios de prueba
  en producción); el reusable saltea el job cuando `stage: pro`.

**Regla dura: los `integration.py` son BLOCK-LOCAL.** El test para el
bloque X **no puede** invocar endpoints HTTP de otro bloque Y. Si Y
cambió en el mismo PR y su package aún no terminó, esa dependencia
introduce carreras inaceptables entre packages en paralelo (y peor: en
un PR que solo toca X, el package de Y ni siquiera correría, y el test
estaría dependiendo silenciosamente del deploy previo). Reglas
concretas:

- Para autenticar el caller, NO llames a `POST /auth/register` desde,
  digamos, files/integration.py. Usa
  `create_test_user_directly()` de `integration_helpers.py`: inserta
  usuario + bearer token vía SQL directo, exactamente con el mismo
  algoritmo que `libs.utils.auth.issue_token`. El token devuelto pasa
  por `require_auth` sin problemas.
- Para datos de catálogo (`banks`, listas estáticas), léelos con `SELECT`
  directo a Postgres. Un `SELECT id FROM banks WHERE is_active LIMIT 1`
  es una lectura al esquema, NO una llamada a la API de otro bloque.
- Para datos de otros dominios (`processes`, `forms`, ...), insertar
  directamente vía SQL siguiendo el schema real (ver
  `platform/migrations/sql/`).
- `signup_and_login()` sigue existiendo en helpers, pero **solo** para
  los `integration.py` DEL PROPIO bloque auth.

**Exclusión del zip**: cada `serverless.yml` incluye
`- '!**/integration.py'` en `package.patterns` para no subirlo a
Lambda.

## 14. Bloques de despliegue

Para evitar re-desplegar todo el proyecto cada vez que se toca un archivo, el
pipeline agrupa el codigo en **bloques** independientes y solo despliega los
bloques afectados por el diff. Un PR abierto NO dispara CI/CD (§15). El deploy
ocurre solo al hacer push a `develop` (→ Deploy DEV) o merge/push a `main` (→
Deploy PRO).

### 14.1 Que es un bloque

| Bloque | Ubicacion | Que es |
|---|---|---|
| `<service>` | `backend/services/<service>/` | Servicio Serverless de dominio de negocio (§5.1). |
| `<name>` | `backend/platform/<name>/` | Bloque de infraestructura runtime (§5.2). |
| `migrations` | `backend/platform/migrations/` | Migraciones SQL versionadas. Ver [`backend/platform/migrations/README.md`](../backend/platform/migrations/README.md). |

Cada carpeta directa bajo `backend/services/` y `backend/platform/` genera
automaticamente un bloque del mismo nombre. Descubrimiento automatico en
[`scripts/ci/plan-deploy.sh`](../scripts/ci/plan-deploy.sh).

### 14.2 Reglas de deploy selectivo

Los bloques `platform/` distinguen entre **contenido** (datos autocontenidos) y
**codigo/config** (que puede afectar a otros bloques). Cambios en contenido
despliegan solo el bloque; cambios en codigo/config disparan **deploy total del
backend**. La lista de subcarpetas de contenido por bloque platform vive en
`PLATFORM_CONTENT_DIRS` dentro de `scripts/ci/plan-deploy.sh`:

| Bloque platform | Subcarpetas de contenido |
|---|---|
| `migrations` | `sql/` |

Tabla exhaustiva de que dispara que:

| Diff detectado en | Bloques a desplegar |
|---|---|
| Solo `backend/services/<X>/**` (uno o varios) | Solo esos servicios |
| Solo `backend/platform/<X>/<content-dir>/**` (ej. `platform/migrations/sql/*.sql`) | Solo `X` |
| Cualquier otra cosa dentro de `backend/platform/<X>/**` (codigo/config del bloque) | **Todos los bloques de backend** |
| Cualquier "backend global" (`serverless-compose.yml`, `config/`, `utils/`, `data/`, `layers/`, `package*.json`, `requirements*.txt`, `.nvmrc`, `.python-version`, `pytest.ini`, `tests/`) | **Todos los bloques de backend** |
| Solo fuera de `backend/` (docs, `.github/`, `scripts/`, `README.md`, `.cursor/rules/`) | **0 deploys** |

Ejemplos concretos:

| Cambio | Plan |
|---|---|
| `backend/services/auth/src/handlers/login/handler.py` | `[auth]` |
| `backend/platform/migrations/sql/20260919_add_users.sql` | `[migrations]` |
| `backend/platform/migrations/src/handlers/apply/handler.py` | **`[migrations, ...todo el backend]`** |
| `backend/platform/migrations/serverless.yml` | **`[migrations, ...todo el backend]`** |
| `backend/config/pytest.ini` | `[migrations, auth, users, ...]` (todo backend) |
| `README.md` o `.github/workflows/deploy-dev.yml` | `[]` (no deploy) |

### 14.3 Orden de despliegue

El modelo mental separa **servicios** (dominios de negocio bajo
`backend/services/<X>/`) de **infraestructura** (bloques bajo
`backend/platform/`, hoy `migrations` y `assets`). Los servicios se
"empaquetan" (validate → test → deploy → integration); la
infraestructura solo se deploya (no tiene test suite propio, es
transversal).

Flujo:

1. **`plan-deploy.sh`** categoriza cada archivo del diff:
   - Cambio en `services/<X>/**` → despliega solo el servicio X.
   - **Cualquier cambio bajo `platform/<infra>/**`** (código o
     contenido — SQL nuevo, asset nuevo, handler de `apply`, etc.) →
     corre ese step de infra Y despliega **TODOS** los servicios.
     Regla cardinal: una migración cambia el esquema de la DB y un
     asset cambia refs embebidas; deployar solo un subconjunto dejaría
     al fleet dividido entre expectativas viejas y nuevas. La
     distinción interna `infra-content` / `infra-code` sigue en el log
     para saber qué disparó el fan-out, pero el efecto es el mismo.
   - **Cualquier otro cambio dentro de `backend/`** (`libs/`,
     `layers/`, `serverless-compose.yml`, `requirements-*.txt`,
     `pytest.ini`, `tests/`, `config/`, `data/`, etc.) → `transversal =
     true` → despliega **TODOS** los servicios. Regla: si se movió
     algo compartido, cualquier servicio puede depender de eso y hay
     que volver a certificar todos.
   - Este fan-out se aplica **también en overrides manuales**:
     `MANUAL_BLOCK=migrations` corre migrations Y redeploya todos los
     servicios, no se puede dejar la infra desincronizada del código.
2. **`infrastructure`** (si el plan lo pidió) corre ANTES que los
   servicios, secuencialmente dentro del mismo job:
   `migrations · deploy → migrations · apply → assets · deploy →
   assets · sync`. Cada sub-step está guardado por su propio flag
   (`run_migrations`, `run_assets`) y salta silenciosamente si no
   aplica.
3. **`services`** corre como matrix en paralelo, una celda por
   servicio en `services_to_deploy`. Cada celda es una llamada al
   reusable `.github/workflows/service-package.yml` que ejecuta
   internamente `validate → test → deploy → integration`. Cada servicio
   tiene su propio stack CloudFormation, correrlos en paralelo baja un
   full-backend deploy de ~15 min a ~5 min.

Dentro de un service package las 4 etapas son estrictamente
secuenciales: si `validate` rompe, `test` no arranca; si `test` rompe,
`deploy` no arranca; si `deploy` rompe, `integration` no arranca (pero
eso no bloquea a otros servicios porque `fail-fast: false` en el
caller). El summary muestra exactamente en qué etapa se cortó cada
servicio.

### 14.4 Override manual

Los workflows `deploy-dev.yml` y `deploy-pro.yml` aceptan un input
`workflow_dispatch`:

- `block` vacio -> auto-detectar del diff.
- `block=<nombre>` -> forzar deploy solo de ese bloque (`auth`, `migrations`, etc.).
- `block=__all__` -> forzar deploy total.

Uso: desde GitHub UI, "Actions" -> el workflow -> "Run workflow" -> completar
el input. Util para re-desplegar un bloque tras rollback o rotar credenciales.

### 14.5 Anti-patrones

- Registrar un bloque "manualmente" en `plan-deploy.sh`. El descubrimiento es
  automatico por el arbol; si necesitas un bloque nuevo, crea la carpeta.
- Poner logica cross-bloque en `backend/services/<X>/` para "no tener que tocar
  `backend/utils/`". Si es cross, va en `backend/utils/` o
  `backend/layers/shared/` aunque eso implique redeploy total.
- Editar un `.sql` de `backend/platform/migrations/sql/` ya mergeado a `main`.
  Ver reglas duras en `backend/platform/migrations/README.md`.

## 15. Flujo de trabajo con GitHub Actions

El pipeline esta optimizado para gastar **minimos minutos** de Actions. Reglas:

| Trigger | Actions que corren |
|---|---|
| `git push feat/*` (o cualquier rama que no sea `main`/`develop`) | **0 workflows** |
| Abrir un PR (a cualquier base) | **0 workflows** |
| Push a `develop` (directo o via merge de PR) | `Deploy DEV` completo |
| Push a `main` (via merge de PR; directo bloqueado) | `Deploy PRO` completo |

Consecuencias practicas:

- **Los PRs no gastan CI**. La branch protection de `main` no exige status
  checks (los quitamos junto con `ci.yml`); solo exige "require PR" para forzar
  revision humana. `develop` no exige ni PR (admite push directo).
- **Checks cross-cutting** (SQL lint, `node --test`, pytest cross-cutting
  de `backend/tests/`) corren en el job global `validate`, una sola vez.
  La **validación por servicio** (`serverless-compose <svc>:package`)
  vive DENTRO del service package, como la primera de las 4 etapas.
  Si `validate` global falla, ni infraestructura ni servicios arrancan
  y AWS queda intacto.
- **Forma canónica del pipeline (servicios vs infraestructura)**:
  - **Deploy DEV**: `plan → validate → infrastructure? → services[matrix] → summary`.
  - **Deploy PRO**: mismo shape, pero cada service package saltea el
    step de `integration` (`stage: pro`; no queremos usuarios de prueba
    en producción).

  `plan` y `validate` corren una sola vez. Después el pipeline se abre
  así:

  ```
  plan → validate → infrastructure?               (only if migrations
                       │                            or assets changed)
                       ├── migrations · deploy    (sequential steps
                       ├── migrations · apply      inside one job)
                       ├── assets · deploy
                       └── assets · sync
                    ↓
                    services (matrix, parallel across services)
                       ├── auth   → validate → test → deploy → integration
                       ├── banks  → validate → test → deploy → integration
                       ├── files  → validate → test → deploy → integration
                       └── ...
                    ↓
                    summary
  ```

  Reglas del layout:
  - **Infraestructura** es un solo job con sub-steps secuenciales
    guardados por `run_migrations` / `run_assets` del plan. Solo corre
    si el plan lo pidió. Un fallo aborta el job (por diseño: si el
    esquema no aplicó, no queremos desplegar código nuevo contra él).
  - **`services` matrix** con `fail-fast: false` y sin `max-parallel`:
    corren completamente en paralelo. Cada celda es una llamada al
    reusable `.github/workflows/service-package.yml`.
  - **Dentro de un service package** las 4 etapas son secuenciales:
    `test` needs `validate`; `deploy` needs `test`; `integration` needs
    `deploy`. Si algo se corta, todo lo posterior se marca `skipped`.
  - **El job `integration`** (§13.3) tiene `continue-on-error: true` y
    solo corre cuando `stage == 'dev'`. Un fallo NO revierte AWS ni
    marca el workflow en rojo — el resultado por servicio queda en el
    `summary` (tabla con las 4 etapas + columna "stopped at") y en el
    artifact `pytest-integration-dev-<service>`.
- **Iteracion sin gastar Actions**: para probar cambios en dev, en vez de mergear
  a `develop`, hacer `sls deploy --stage dev` directamente desde local con
  credenciales AWS locales. Cuando este todo validado, un unico PR/merge a `main`
  dispara Deploy PRO. El commit puede incluir `[skip ci]` en el cuerpo para
  reforzar la intencion (pero en el nuevo esquema es redundante: los PRs ya no
  disparan nada).
- Si se necesita ahorrar aun un Deploy DEV (por ejemplo, cambios que solo tocan
  docs o `.github/`), el propio `plan-deploy.sh` devuelve `[]` y el job
  `deploy` se salta gracias a `if: needs.plan.outputs.count != '0'`.

