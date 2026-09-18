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

## 4. Layout del monorepo

La raíz del repo agrupa **infraestructura de proyecto**; el runtime backend vive
completo bajo [`backend/`](../backend/).

```
repo/
├── .github/workflows/          ← CI/CD YAMLs
├── .cursor/rules/              ← reglas persistentes IA
├── docs/                       ← documentacion humana
├── scripts/iam/                ← IAM bootstrap docs + JSON policy
├── backend/                    ← ★ TODO el backend Serverless
│   ├── serverless-compose.yml
│   ├── package.json, package-lock.json
│   ├── requirements-dev.txt, pytest.ini
│   ├── .nvmrc, .python-version
│   ├── config/, utils/, data/    (§7)
│   ├── services/<service>/       (§5)
│   ├── layers/shared/            (Lambda Layer)
│   └── tests/
├── README.md, CONTRIBUTING.md
└── .gitignore
```

Todo el trabajo de Lambda, Serverless, dependencias Python/Node y tests unitarios
ocurre dentro de `backend/`. La raíz permanece "agnóstica" para dejar espacio a un
futuro `frontend/` sin conflictos.

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

Estructura de un servicio `signature` con una Lambda HTTP `create-signature`,
un worker `sign` y un scheduled `cleanup-expired-otps`:

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

`backend/services/signature/serverless.yml`:

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
  # Fuerza cdts-<stage>-<service>-<function> en vez del default de Serverless.
  naming:
    functionName: cdts-${self:provider.stage}-signature-${self:function.name}

functions:
  create-signature:      ${file(./src/handlers/create-signature/function.yml)}
  sign:                  ${file(./src/workers/sign/function.yml)}
  cleanup-expired-otps:  ${file(./src/scheduled/cleanup-expired-otps/function.yml)}
```

`backend/services/signature/src/handlers/create-signature/function.yml`:

```yaml
handler: src/handlers/create-signature/handler.handler
events:
  - httpApi:
      method: POST
      path: /signatures
environment:
  SIGNATURES_TABLE: !Ref SignaturesTable
```

`backend/services/signature/src/handlers/create-signature/handler.py`:

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

Para evitar re-desplegar todo el backend cada vez que se toca un archivo, el
pipeline agrupa el codigo en **bloques** independientes y solo despliega los
bloques afectados por el diff.

### 14.1 Que es un bloque

Un bloque es una unidad autonoma que se despliega junta. Los bloques que existen
hoy o pueden existir bajo `backend/`:

| Bloque | Ubicacion | Que es |
|---|---|---|
| `<service>` | `backend/services/<service>/` | Servicio Serverless de dominio de negocio (§5.1). |
| `<name>` | `backend/platform/<name>/` | Bloque de infraestructura runtime (§5.2). |
| `migrations` | `backend/platform/migrations/` | Migraciones SQL versionadas. Ver [`backend/platform/migrations/README.md`](../backend/platform/migrations/README.md). |

Cada carpeta directa bajo `backend/services/` y `backend/platform/` genera
automaticamente un bloque del mismo nombre. No hay que registrarlo en ningun
lado extra: el [`scripts/ci/plan-deploy.sh`](../scripts/ci/plan-deploy.sh)
descubre los bloques leyendo el arbol.

### 14.2 Reglas de deploy selectivo

1. **Cambios solo dentro de `backend/services/<X>/`** -> se despliega solo el
   bloque `X`.
2. **Cambios solo dentro de `backend/platform/<X>/`** -> se despliega solo el
   bloque `X` (por ejemplo `migrations`).
3. **Cambios en varios bloques a la vez** -> se despliegan todos los afectados,
   en orden: `migrations` primero, despues el resto alfabetico.
4. **Cambios en cualquier archivo backend/ que NO pertenezca a un bloque** ->
   se re-despliegan **TODOS** los bloques. Regla conservadora: cualquier cosa
   en `backend/` fuera de `services/<X>/` o `platform/<X>/` se considera cross
   por defecto. Ejemplos tipicos:
   - `backend/serverless-compose.yml`
   - `backend/package.json`, `backend/package-lock.json`
   - `backend/requirements-dev.txt`, `backend/requirements.txt`
   - `backend/.nvmrc`, `backend/.python-version`, `backend/pytest.ini`
   - `backend/config/**`
   - `backend/utils/**`
   - `backend/data/**`
   - `backend/layers/**`
5. **Cambios solo fuera de `backend/`** (docs, workflows, `.cursor/rules/`,
   `scripts/iam/`, etc.) -> **no se despliega nada**. Solo corre CI.
6. **Frontend** (cuando exista, en `frontend/`) siempre despliega **completo**;
   no habra sub-bloques dentro. Se define en su propio workflow.

### 14.3 Orden de despliegue

Cuando el plan incluye varios bloques, se despliegan **secuencialmente** con
`max-parallel: 1`. `migrations` va siempre primero para garantizar que el
esquema este al dia antes de que arranquen los servicios.

### 14.4 Override manual

Los workflows `deploy-dev.yml` y `deploy-pro.yml` aceptan un input
`workflow_dispatch`:

- `block` vacio -> auto-detectar del diff.
- `block=<nombre>` -> forzar deploy solo de ese bloque.
- `block=__all__` -> forzar deploy total.

Uso: desde GitHub UI, "Actions" -> el workflow -> "Run workflow" -> completar
el input. Util para re-desplegar un bloque tras una rollback, o para redesplegar
todo tras rotar credenciales.

### 14.5 Preview en PR

El `ci.yml` incluye un job `plan-preview` que corre `scripts/ci/plan-deploy.sh`
en modo `DRY_RUN=1`. En el summary de la PR aparece el listado de bloques que se
desplegarian tras el merge. Es informativo; el plan real se recalcula post-merge
usando el diff efectivo entre el commit anterior y el nuevo HEAD.

### 14.6 Anti-patrones

- Registrar un bloque "manualmente" en `plan-deploy.sh`. El descubrimiento es
  automatico por el arbol; si necesitas un bloque nuevo, crea la carpeta.
- Poner logica cross-bloque en `backend/services/<X>/` para "no tener que tocar
  `backend/utils/`". Si es cross, va en `backend/utils/` o
  `backend/layers/shared/` aunque eso implique redeploy total.
- Editar un `.sql` de `backend/migrations/sql/` ya mergeado a `main`. Ver reglas
  duras en `backend/migrations/README.md`.

