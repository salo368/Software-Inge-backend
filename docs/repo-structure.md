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
| Referencia en `function.yml` | slashes + `.handler` | `handler: src/handlers/refresh_token/handler.handler` |
| Nombre AWS de la Lambda | `kebab-case`, se declara **explícito** con `name:` en el `function.yml` | `name: cdts-${sls:stage}-auth-refresh-token` |

Regla mnemotécnica: **en la carpeta usás `_`; en el nombre AWS ese `_` se vuelve `-`**.

**No** usar `provider.naming.functionName` en el `serverless.yml` — esa
propiedad no existe en Serverless Framework 3 y falla con
`Cannot resolve variable at "provider.naming.functionName"`. En su lugar:

- `provider.stackName: cdts-${sls:stage}-<service>` — nombre del CFN stack.
- `functions.<key>.name: cdts-${sls:stage}-<service>-<function>` (dentro de
  cada `function.yml`) — nombre AWS de la Lambda.

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

## 4. Layout del monorepo

La raíz del repo agrupa **infraestructura de proyecto**; el runtime backend vive
completo bajo [`backend/`](../backend/) y el frontend bajo [`frontend/`](../frontend/).

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
├── frontend/                   ← ★ Angular SPA (bloque unico, §5.4)
│   ├── serverless.yml            (S3 + CloudFront + OAC)
│   ├── angular.json, package.json
│   └── src/
├── README.md, CONTRIBUTING.md
└── .gitignore
```

Todo el trabajo de Lambda, Serverless backend, dependencias Python/Node de
backend y tests unitarios ocurre dentro de `backend/`. Todo el trabajo del cliente
web (Angular) ocurre dentro de `frontend/`. La raíz permanece "agnóstica".

## 5. Servicios de dominio vs bloques de plataforma

El backend tiene dos tipos de bloques desplegables. Los dos se registran igual en
`backend/serverless-compose.yml`, tienen la misma estructura interna de código
Serverless, y son unidades de deploy independientes. Se separan **solo por
convención** para dejar clara la intención:

### 5.1 `backend/services/<name>/` — DOMINIO DE NEGOCIO

Cada carpeta bajo `backend/services/` es un **servicio** que representa **un solo
dominio** (bounded context). Ejemplos: `access`, `signature`, `payments`.

- Un servicio nunca importa código de otro servicio directamente.
- Lo compartido va en `backend/layers/shared/` (Lambda Layer publicada por su propio
  micro-serverless).

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

### 5.4 `frontend/` — SPA Angular (bloque único)

Fuera de `backend/`, a nivel raíz, existe un único bloque `frontend`. No se
subdivide: cualquier cambio dentro de `frontend/**` dispara el deploy completo
del bloque.

- Stack: **Angular 18** con builder `@angular-devkit/build-angular:application`.
- Infra AWS: **S3 privado + CloudFront con Origin Access Control (OAC)**. Bucket
  bloqueado, sólo CloudFront lee (via bucket policy con condition `aws:SourceArn`).
- Definición: `frontend/serverless.yml` con `service: frontend`. Sin Lambdas;
  solo `resources`. `package.patterns: ['!./**']` para no subir nada como zip.
- Naming CFN: `stackName: cdts-${sls:stage}-frontend`. Bucket:
  `cdts-<stage>-frontend-web-<accountId>` (sufijo del accountId para garantizar
  unicidad global).
- Configuraciones Angular: `dev` y `pro` (renombradas de las default `development`
  y `production`). `pro` incluye `fileReplacements` para reemplazar
  `src/environments/environment.ts` por `environment.pro.ts`.
- Deploy real (job de CI para el bloque `frontend`):
  1. `sls deploy --stage <stage>` — crea/actualiza infra CFN.
  2. `ng build --configuration <stage>` — genera `dist/cdts-frontend/browser/`.
  3. [`scripts/ci/deploy-frontend.sh`](../scripts/ci/deploy-frontend.sh) — sube
     los assets a S3 **con Content-Type explícito por extensión** (evita el bug
     de `aws s3 sync` en Windows que sirve `.js` como `text/plain` y rompe la SPA),
     aplica `Cache-Control: public, max-age=31536000, immutable` en assets
     hasheados (js/css/svg/woff2/json) y `no-cache` en `index.html`, borra
     archivos huérfanos con `aws s3 sync --delete --size-only`, y crea la
     invalidación de CloudFront.
- CloudFront devuelve `/index.html` (200) para 403/404 → SPA routing client-side.

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
exactamente dos archivos**:

- `handler.py` — código Python (define la función `handler(event, context)`).
- `function.yml` — configuración Serverless de esa función. Se referencia desde
  `serverless.yml` con `${file(./src/<tipo>/<function>/function.yml)}`.

Si una Lambda necesita más de un archivo, esos archivos van dentro de la misma carpeta
de la Lambda, no fuera.

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

functions:
  create_signature:     ${file(./src/handlers/create_signature/function.yml)}
  sign:                 ${file(./src/workers/sign/function.yml)}
  cleanup_expired_otps: ${file(./src/scheduled/cleanup_expired_otps/function.yml)}
```

`backend/services/signature/src/handlers/create_signature/function.yml`:

```yaml
# name = cdts-<stage>-<servicio>-<carpeta con _ reemplazado por ->
name: cdts-${sls:stage}-signature-create-signature
handler: src/handlers/create_signature/handler.handler
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
  `provider.stackName` para el CFN stack y `name:` explícito en cada `function.yml`.
- Uso de dots (`src.handlers.login.handler.handler`) en el `handler:`. La
  convención es slashes: `src/handlers/login/handler.handler`.
- `- http:` (API Gateway v1) por default. Usar `- httpApi:` (v2); v1 sólo si
  necesitás WAF o endpoints privados.
- CORS repetido dentro de cada `function.yml`. Va una sola vez en
  `provider.httpApi.cors`.
- Archivos del backend (Python, `serverless.yml`, `requirements-*.txt`, etc.) fuera
  de `backend/`. La raíz permanece para infra de proyecto y para un eventual `frontend/`.

## 13. Tests

Los tests viven en `backend/tests/`, espejando la estructura de servicios:

```
backend/tests/
├── test_access_login.py
├── test_signature_create_signature.py
└── ...
```

Cada test es del tipo pytest (`test_*.py`, funciones `test_*`). El CI corre
`pytest tests -ra` **dentro de `backend/`** en cada PR.

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
| `frontend` | `frontend/` | SPA Angular (§5.4). Bloque **unico**, no se subdivide. |

Cada carpeta directa bajo `backend/services/` y `backend/platform/` genera
automaticamente un bloque del mismo nombre. El bloque `frontend` es unico y
existe siempre que exista la carpeta `frontend/`. Descubrimiento automatico
en [`scripts/ci/plan-deploy.sh`](../scripts/ci/plan-deploy.sh).

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
| Solo `frontend/**` | Solo `frontend` |
| Mezcla backend + frontend | Los del backend segun reglas de arriba **+** `frontend` |
| Solo fuera de `backend/` y `frontend/` (docs, `.github/`, `scripts/`, `README.md`, `.cursor/rules/`) | **0 deploys** |

Ejemplos concretos:

| Cambio | Plan |
|---|---|
| `backend/services/auth/src/handlers/login/handler.py` | `[auth]` |
| `backend/platform/migrations/sql/20260919_add_users.sql` | `[migrations]` |
| `backend/platform/migrations/src/handlers/apply/handler.py` | **`[migrations, ...todo el backend]`** |
| `backend/platform/migrations/serverless.yml` | **`[migrations, ...todo el backend]`** |
| `backend/config/pytest.ini` | `[migrations, auth, users, ...]` (todo backend) |
| `frontend/src/app/app.component.html` | `[frontend]` |
| `backend/services/auth/**` + `frontend/**` | `[auth, frontend]` |
| `README.md` o `.github/workflows/deploy-dev.yml` | `[]` (no deploy) |

### 14.3 Orden de despliegue

Cuando el plan incluye varios bloques, se despliegan **secuencialmente** con
`max-parallel: 1`, en este orden:

1. `migrations` primero (si aplica). Asegura que el esquema este al dia.
2. Resto del backend en orden alfabetico.
3. `frontend` al final (si aplica). Asegura que la SPA consuma endpoints ya
   desplegados.

### 14.4 Override manual

Los workflows `deploy-dev.yml` y `deploy-pro.yml` aceptan un input
`workflow_dispatch`:

- `block` vacio -> auto-detectar del diff.
- `block=<nombre>` -> forzar deploy solo de ese bloque (`auth`, `migrations`, `frontend`, etc.).
- `block=__all__` -> forzar deploy total (todo el backend + frontend).

Uso: desde GitHub UI, "Actions" -> el workflow -> "Run workflow" -> completar
el input. Util para re-desplegar un bloque tras rollback o rotar credenciales.

### 14.5 Anti-patrones

- Registrar un bloque "manualmente" en `plan-deploy.sh`. El descubrimiento es
  automatico por el arbol; si necesitas un bloque nuevo, crea la carpeta.
- Poner logica cross-bloque en `backend/services/<X>/` para "no tener que tocar
  `backend/utils/`". Si es cross, va en `backend/utils/` o
  `backend/layers/shared/` aunque eso implique redeploy total.
- Meter un subproyecto dentro de `frontend/` para "no re-desplegar todo el
  frontend". Frontend es un bloque unico por diseno; si aparece la necesidad
  de subdividir, se replantea la regla.
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
- **Todos los checks del ex-`ci.yml`** (pytest, lint-migrations, `serverless-compose
  package`) corren ahora en el job `validate` dentro de `Deploy DEV` y `Deploy PRO`.
  Si `validate` falla, `plan` y `deploy` no se ejecutan y AWS queda intacto.
- **Iteracion sin gastar Actions**: para probar cambios en dev, en vez de mergear
  a `develop`, hacer `sls deploy --stage dev` directamente desde local con
  credenciales AWS locales. Cuando este todo validado, un unico PR/merge a `main`
  dispara Deploy PRO. El commit puede incluir `[skip ci]` en el cuerpo para
  reforzar la intencion (pero en el nuevo esquema es redundante: los PRs ya no
  disparan nada).
- Si se necesita ahorrar aun un Deploy DEV (por ejemplo, cambios que solo tocan
  docs o `.github/`), el propio `plan-deploy.sh` devuelve `[]` y el job
  `deploy` se salta gracias a `if: needs.plan.outputs.count != '0'`.

