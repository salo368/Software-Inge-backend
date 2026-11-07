# Referencia técnica del backend — handlers, clases, librerías y despliegue

Este documento es una referencia INTERNA de implementación de
`Software-Inge-backend`: a diferencia de los manuales de API ya existentes
en este mismo directorio (`auth-api.md`, `banks-api.md`, etc., pensados para
consumir los endpoints desde afuera), este documento explica **cómo está
construido el código por dentro** — cada handler, cada clase y método,
cómo se auto-registran las funciones Lambda, y el mecanismo real de build y
despliegue.

Generado a partir de una lectura directa del código fuente (no de memoria ni
de suposiciones) contra el estado de `develop` del 2026-11-06, más una
sección final sobre `documents` (caso de uso C11) que documenta la rama
`feat/documents-c11-basic-flow`, todavía pendiente de merge en ese momento —
marcada explícitamente como tal.

## Índice

1. Servicio `auth`
2. Servicio `banks`
3. Servicio `files`
4. Servicio `forms`
5. Servicio `processes`
6. Servicio `signatures`
7. Librerías compartidas (`backend/libs/`)
8. Mecanismo de build y despliegue
9. Servicio `documents` (C11 — pendiente de merge a `develop`)

---


---

## 1. Servicio `auth`

### Propósito

El servicio `auth` concentra toda la gestión de identidad del backend: alta de cuentas, inicio y cierre de sesión, y resolución del usuario autenticado a partir de un token. Las entidades de negocio que maneja son `users` (cuenta de usuario: `id` UUID, `email`, `full_name`, timestamps), `user_credentials` (hash de contraseña asociado 1:1 a un `user_id`, separado de `users` para no mezclar datos de identidad con material sensible) y `bearer_tokens` (tokens opacos emitidos al autenticar, con expiración y revocación explícita). No implementa OAuth ni sesiones basadas en cookies: el mecanismo es un bearer token propio, generado con `secrets.token_urlsafe`, cuyo hash SHA-256 se persiste en base de datos (nunca el token en texto plano) y que vence a las 24 horas o puede revocarse manualmente vía `/auth/logout`.

Los cuatro handlers (`login`, `logout`, `me`, `register`) cubren el ciclo completo de autenticación: `register` crea la cuenta y las credenciales y devuelve un token ya emitido (login implícito tras el registro); `login` valida credenciales existentes y emite un nuevo token; `me` resuelve "quién soy" a partir del token recibido; `logout` revoca el token actual. Toda la lógica de verificación de contraseña, emisión/validación de tokens y hashing vive en `backend/libs`, de modo que otros servicios puedan reutilizar `require_auth` sin duplicar reglas de negocio de autenticación.

### Arquitectura de despliegue

**`serverless.yml`**

- `provider`: `name: aws`, `runtime: python3.12`, `region` parametrizable por `--region` (default `us-east-1`), `stage` parametrizable por `--stage` (default `dev`), `stackName: cdts-${sls:stage}-auth`, `memorySize: 512`, `timeout: 15` (segundos), `logRetentionInDays: 14` (los logs de CloudWatch de cada función se retienen 14 días y luego se purgan automáticamente).
- `httpApi.cors: true`: habilita CORS por defecto en el API Gateway HTTP API (API de tipo `httpApi`, no `rest`) que expone las funciones de este servicio, sin restringir orígenes explícitamente.
- `environment` (variables inyectadas a **todas** las funciones del servicio):
  - `STAGE: ${sls:stage}` — identifica el ambiente de despliegue (dev/staging/prod) en runtime.
  - `SSM_DB_PATH: /cdts/${sls:stage}/db` — ruta base en AWS SSM Parameter Store desde donde `libs/core/db.py` recupera las credenciales de conexión a la base de datos Postgres para el stage activo.
- `iam.role`: se crea un rol dedicado `cdts-${sls:stage}-auth-lambda` (no se reutiliza el rol por defecto de Serverless) con un único statement: `Effect: Allow`, `Action: ssm:GetParametersByPath` sobre los ARN `arn:aws:ssm:${aws:region}:*:parameter/cdts/${sls:stage}/db` y su wildcard `/db/*`. Es decir, el servicio solo tiene permiso de leer (por prefijo) los parámetros de conexión a base de datos bajo su stage; no tiene acceso a S3, SQS, ni a otros parámetros SSM.
- `plugins: serverless-python-requirements` — plugin que empaqueta las dependencias de `requirements.txt` dentro del paquete de deployment de cada Lambda.
- `custom.pythonRequirements`: `dockerizePip: false` (instala las dependencias con el Python local, sin contenedor Docker — asume que el entorno de build ya es compatible con Lambda/Linux o que las libs son puras), `slim: false` (no se eliminan archivos de bytecode/tests de las dependencias para reducir tamaño), `fileName: requirements.txt` (usa ese archivo como fuente de paquetes a instalar).
- `package.patterns`: arranca excluyendo todo (`!**`) y luego incluye explícitamente `src/**` y `libs/**` (el mirror local de `backend/libs`, ver más abajo), excluyendo `__pycache__`, `*.pyc` y los archivos de test colocados junto a cada handler (`test.py`, `integration.py`, `conftest.py`) para que no viajen en el ZIP de despliegue.
- `resources`: el archivo no define un bloque `resources` — este servicio no crea tablas, colas ni buckets propios vía CloudFormation; las tablas (`users`, `user_credentials`, `bearer_tokens`) ya existen en la base de datos Postgres compartida, administrada fuera de este servicio.

**`requirements.txt`**

- `sqlalchemy==2.0.34` — ORM/Core usado por `backend/libs/orm/*` (incluye `Users`, `UserCredentials`, `BearerTokens`) para construir `select`/`insert` y mapear filas a objetos.
- `pg8000==1.31.2` — driver puro-Python de PostgreSQL usado como `dialect+driver` de SQLAlchemy (evita dependencias compiladas como `psycopg2`, más simple de empaquetar para Lambda).
- `scramp==1.4.17` — implementa el mecanismo de autenticación SCRAM que `pg8000` necesita para autenticarse contra Postgres cuando el servidor exige `scram-sha-256`.
- `bcrypt==4.2.0` — usado por `libs/utils/passwords.py` para hashear y verificar contraseñas (`hash_password`/`verify_password`); es la única dependencia nativa/compilada del servicio, confinada deliberadamente a este módulo (ver comentario en el propio archivo).

**Auto-registro de handlers (`functions.js` + `utils/build-functions.js`)**

`services/auth/functions.js` primero sincroniza el código común: borra `services/auth/libs` (carpeta ignorada por git) y copia allí todo `backend/libs`, de modo que cuando Serverless empaquete `libs/**` (según el patrón declarado en `serverless.yml`) incluya la última versión de las librerías compartidas dentro del ZIP de cada Lambda. Luego delega la construcción del mapa `functions` a `backend/utils/build-functions.js`, pasándole `__dirname` (la carpeta del servicio) como `serviceDir`.

`build-functions.js` exporta una función que Serverless invoca de forma asíncrona (recibe `{ options, resolveConfigurationProperty }`) para resolver `functions: ${file(./functions.js):build}`. El mecanismo es:

1. Resuelve `service` (nombre del servicio, `auth`) y `stage` (de `--stage`/`-s`, default `dev`).
2. Recorre tres subcarpetas posibles bajo `src/`: `handlers`, `scheduled`, `workers` (en ese orden fijo) — si una no existe, se omite. En `auth` solo existe `src/handlers`.
3. Dentro de cada una, lista las subcarpetas (orden alfabético, vía `fs.readdirSync(...).sort()`) y, para cada una que sea un directorio, exige que exista un `function.yml`; si falta, lanza un error que detiene el despliegue (`Missing function.yml in ...`).
4. Valida que el nombre de carpeta sea snake_case (`^[a-z][a-z0-9_]*$`) porque debe ser importable como módulo Python; si no, lanza error explicando que Python no puede importar carpetas con guiones.
5. Carga el `function.yml` de la carpeta (vía `js-yaml`) como objeto `custom`, y construye la entrada final de la función como:
   - `name: cdts-${stage}-${service}-${folderKebab}` (el folder con `_` convertido a `-`; p.ej. `login` → `cdts-dev-auth-login`).
   - `handler: src/${type}/${folder}/handler.handler` (p.ej. `src/handlers/login/handler.handler`, apuntando a la función `handler` dentro de `handler.py`).
   - `...custom` — todo lo que venga en `function.yml` se mezcla *después*, así que si el YAML define explícitamente `name` o `handler` esos valores ganan (son el "escape hatch" documentado en el propio comentario del archivo); normalmente `function.yml` solo aporta `description` y `events`.

En los cuatro handlers de `auth`, ningún `function.yml` sobreescribe `name`/`handler`: cada uno solo declara `description` y un evento `httpApi` con método y path explícitos (p.ej. `POST /auth/login`), así que el nombre final de la función Lambda sigue siempre el patrón automático.

### Handlers

Carpetas bajo `src/handlers/`, en el orden en que aparecen en el filesystem: `login`, `logout`, `me`, `register`.

#### `login`

- **Trigger**: `function.yml` declara `httpApi: { method: POST, path: /auth/login }`.
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions`.
- **Flujo**: parsea el body JSON (`json.loads(event.get("body") or "{}")`), normaliza `email` (strip + lowercase) y toma `password` tal cual. Si falta `email` o `password`, lanza `HandledError("missing_fields", 400)`. Busca el usuario por email (`Users.get_by_email`); si no existe, responde `HandledError("invalid_credentials", 401)` (mismo código que una contraseña incorrecta, para no filtrar si el email está registrado). Obtiene las credenciales del usuario (`UserCredentials.get_by_user_id`) y verifica la contraseña con `verify_password`; si las credenciales no existen o la verificación falla, vuelve a responder `invalid_credentials` (401). Si todo es válido, emite un token con `issue_token(user.id)` y devuelve 200 con el usuario serializado (`id`, `email`, `full_name`, `created_at`/`updated_at` en ISO 8601), el `token` en texto plano y su `expires_at`.
- **Librerías de `backend/libs` usadas**: `libs.core.responses.HandledError`/`generate_response`/`handle_exceptions` para las respuestas y el manejo uniforme de errores; `libs.orm.users.Users` y `libs.orm.user_credentials.UserCredentials` para las consultas; `libs.utils.auth.issue_token` para generar el bearer token; `libs.utils.passwords.verify_password` para comparar el hash bcrypt.
- **Decoradores**: `@handle_exceptions` envuelve toda la ejecución en un `try/except`: si se lanza un `HandledError`, hace `rollback()` de la sesión de DB, lo loguea como `WARNING` y devuelve `generate_response({"error": ...}, status_code)` con el código que traiga la excepción; cualquier otra excepción se trata como error 500 (`internal_server_error`), logueada como `ERROR` con traceback; en el camino feliz hace `db_session.commit()` tras ejecutar el handler. En el `finally` siempre cierra la sesión (`db_session.close()`), necesario porque la sesión es un singleton a nivel de módulo que puede sobrevivir entre invocaciones en un contenedor "caliente" de Lambda.

#### `logout`

- **Trigger**: `httpApi: { method: POST, path: /auth/logout }`.
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions` y `@require_auth` (en ese orden de aplicación: `require_auth` corre primero porque es el decorador más interno).
- **Flujo**: no valida ningún body; asume que `require_auth` ya dejó `event["token"]` con el objeto `BearerTokens` correspondiente al token recibido. Llama a `revoke(token.id)` (de `libs.utils.bearer_tokens`), que marca `revoked_at` en la fila del token, y responde 200 con `{"revoked": True}`.
- **Librerías usadas**: `libs.core.responses.generate_response`/`handle_exceptions`; `libs.utils.auth.require_auth`; `libs.utils.bearer_tokens.revoke`.
- **Decoradores**: `@require_auth` (definido en `libs/utils/auth.py`) extrae el header `Authorization`, exige que empiece con `Bearer ` (case-insensitive) y que tenga un token no vacío tras el prefijo; si falta o está vacío, corta con `HandledError` 401 (`missing_bearer_token` o `invalid_or_expired_token`). Busca el `BearerTokens` por el hash SHA-256 del token; si no existe, está revocado (`revoked_at is not None`) o ya expiró (`is_alive` devuelve `False`), responde 401 `invalid_or_expired_token` en cada caso. Si el token es válido, resuelve el `Users.get_by_id(bearer.user_id)`; si el usuario ya no existe, también 401. Finalmente inyecta `event["user"]` y `event["token"]` antes de invocar el handler real — por eso `logout` puede leer `event.get("token")` sin validarlo de nuevo.

#### `me`

- **Trigger**: `httpApi: { method: GET, path: /auth/me }`.
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions` y `@require_auth`.
- **Flujo**: toma `event.get("user")` (ya inyectado por `require_auth`) y devuelve 200 con el usuario serializado (`id`, `email`, `full_name`, `created_at`, `updated_at`). No toca la base de datos directamente — toda la resolución de identidad ocurre en el decorador.
- **Librerías usadas**: `libs.core.responses.generate_response`/`handle_exceptions`; `libs.utils.auth.require_auth`.
- **Decoradores**: mismo `require_auth` descrito arriba; es el único trabajo real de este handler.

#### `register`

- **Trigger**: `httpApi: { method: POST, path: /auth/register }`.
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions`.
- **Flujo**: parsea el body, normaliza `email` y `full_name` (strip/lowercase donde aplica) y toma `password`. Si falta cualquiera de los tres campos, `HandledError("missing_fields", 400)`. Valida formato de email con `valid_email`; si es inválido, `HandledError("invalid_email", 400)`. Valida la fortaleza de la contraseña con `password_reason` (longitud mínima 10, al menos una letra y un dígito); si devuelve una razón, se lanza `HandledError(reason, 400)` con ese código específico (`password_too_short`, `password_needs_letter`, etc.). Verifica que el email no esté ya registrado (`Users.get_by_email`); si existe, `HandledError("email_taken", 409)`. Si todas las validaciones pasan, crea el usuario (`Users.create`) y sus credenciales (`UserCredentials.create` con `hash_password(password)`), emite un token (`issue_token`) y responde **201** con el usuario, el token y su expiración — register deja al usuario autenticado de inmediato, sin requerir un login separado.
- **Librerías usadas**: `libs.core.responses.HandledError`/`generate_response`/`handle_exceptions`; `libs.orm.users.Users`; `libs.orm.user_credentials.UserCredentials`; `libs.utils.auth.issue_token`; `libs.utils.passwords.hash_password`; `libs.utils.validators.password_reason`/`valid_email`.
- **Decoradores**: solo `@handle_exceptions` (no requiere autenticación, es el punto de entrada para crear la cuenta).

### Clases y métodos de dominio propios del servicio

El servicio `auth` no tiene una carpeta `domain/` ni una carpeta `utils/` propia bajo `services/auth/src/`. Toda la lógica de dominio (modelos ORM, hashing, validadores, emisión/verificación de tokens) está centralizada en `backend/libs` (compartida con otros servicios) y se referencia desde cada `handler.py` como se detalla arriba; no existe código de dominio exclusivo de este servicio más allá de los propios handlers.

---

## 2. Servicio `banks`

### Propósito

El servicio `banks` expone el catálogo de bancos participantes del producto de CDT (Certificado de Depósito a Término) y el motor de simulación de rendimiento. La entidad de negocio central es `banks` (id, `code`, `name`, claves de assets `logo_key`/`io_key`, `description`, `tier`, `rating_by`, `highlights`, `is_active`), complementada por tres tablas de tasas que no tienen handler propio pero sí se consultan a través de `libs/utils/rates.py`: `rates` (tasa efectiva anual por combinación de bandas), `rates_amount_band` (bandas de monto por banco) y `rates_term_band` (bandas de plazo por banco). El servicio no escribe en ninguna de estas tablas — es de solo lectura; la administración de bancos y tasas se asume hecha por otro proceso (back-office) fuera de este servicio.

Los tres handlers cubren: listar bancos activos (`get_banks`), consultar el detalle de un banco puntual incluyendo la plantilla de orden de inversión vacía para firma (`get_bank`), y simular, dado un monto y un plazo, qué tasa aplicaría cada banco y cuál sería el interés/monto final resultante (`simulate`), rankeando los bancos candidatos. A diferencia de `auth`, ninguno de estos handlers requiere autenticación (`@require_auth`) — son endpoints de consulta pública de catálogo e información comercial.

### Arquitectura de despliegue

**`serverless.yml`**

- `provider`: idéntico en forma a `auth` — `runtime: python3.12`, región/stage parametrizables, `stackName: cdts-${sls:stage}-banks`, `memorySize: 512`, `timeout: 15`, `logRetentionInDays: 14`.
- `httpApi.cors: true`: mismo esquema de CORS abierto por defecto para el HTTP API de este servicio.
- `environment`:
  - `STAGE: ${sls:stage}` — igual que en `auth`, identifica el ambiente activo.
  - `SSM_DB_PATH: /cdts/${sls:stage}/db` — misma ruta de SSM para las credenciales de conexión a la base de datos.
  - `ASSETS_BASE_URL: https://cdts-${sls:stage}-assets.s3.${aws:region}.amazonaws.com` — URL base del bucket S3 de assets (por stage y región) que `get_bank`, `get_banks` y `simulate` usan para construir las URLs públicas de `logo_url`/`io_url` a partir de las claves (`logo_key`/`io_key`) guardadas en la tabla `banks`. Esta variable no existe en `auth`, que no sirve assets.
- `iam.role`: rol dedicado `cdts-${sls:stage}-banks-lambda` con el mismo (y único) statement que `auth`: `ssm:GetParametersByPath` sobre `arn:aws:ssm:${aws:region}:*:parameter/cdts/${sls:stage}/db` y su wildcard. El servicio no tiene permisos IAM sobre S3 pese a construir URLs de ese bucket: como solo arma URLs públicas por convención de nombre (no hace `GetObject`/`PutObject` ni usa el SDK de S3), no necesita permisos sobre el bucket de assets.
- `plugins`/`custom.pythonRequirements`: exactamente igual que `auth` (`serverless-python-requirements`, `dockerizePip: false`, `slim: false`, `fileName: requirements.txt`).
- `package.patterns`: idénticos a `auth` (incluye `src/**` y `libs/**`, excluye `__pycache__`, `*.pyc`, `test.py`, `integration.py`, `conftest.py`).
- `resources`: no se define bloque `resources` — tampoco crea infraestructura de datos propia; lee de las tablas `banks`, `rates`, `rates_amount_band` y `rates_term_band` ya existentes en la base compartida.

**`requirements.txt`**

- `sqlalchemy==2.0.34` — igual que en `auth`, usado por `libs/orm/banks.py`, `libs/orm/rates.py`, `libs/orm/rates_amount_band.py` y `libs/orm/rates_term_band.py` para las consultas `select`.
- `pg8000==1.31.2` — driver Postgres puro-Python, mismo rol que en `auth`.
- `scramp==1.4.17` — mecanismo SCRAM requerido por `pg8000` para autenticar contra Postgres.

A diferencia de `auth`, `banks` **no** incluye `bcrypt`: no maneja contraseñas ni hashing, solo lectura de catálogo y cálculo numérico (con `decimal.Decimal`, de la librería estándar).

**Auto-registro de handlers**

Mecánica idéntica a `auth`: `services/banks/functions.js` borra y recrea `services/banks/libs` como copia de `backend/libs`, y delega en `backend/utils/build-functions.js` la construcción del mapa `functions` a partir de `services/banks/src/handlers/*`. Las tres carpetas (`get_bank`, `get_banks`, `simulate`) son snake_case válidas, cada una con su `function.yml` que solo aporta `description` y el evento `httpApi` correspondiente — ninguna sobreescribe `name` ni `handler`, así que el nombre final sigue el patrón `cdts-${stage}-banks-<folder-con-guiones>` (p.ej. `get_bank` → `cdts-dev-banks-get-bank`) y el path al módulo es siempre `src/handlers/<folder>/handler.handler`.

### Handlers

Carpetas bajo `src/handlers/`, en el orden del filesystem: `get_bank`, `get_banks`, `simulate`.

#### `get_bank`

- **Trigger**: `function.yml` → `httpApi: { method: GET, path: /banks/get-bank }`. La descripción del propio `function.yml` aclara el propósito del campo `io_url`: "the empty investment-order template, for generate_sign to populate and sign" (vincula este endpoint con un flujo externo de generación/firma de formularios de inversión, no implementado en este handler).
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions`.
- **Flujo**: lee `bank_id` de `event.get("queryStringParameters")`; intenta convertirlo a `int` y, si falla (ausente, no numérico), responde `HandledError("invalid bank_id", 400)`. Busca el banco con `Banks.get_by_id(bank_id)`; si no existe, `HandledError("bank_not_found", 404)`. Si existe, serializa todos los campos del banco a 200, resolviendo `logo_url` e `io_url` a través de la función local `_asset_url(key)` (concatena `ASSETS_BASE_URL` + la clave, evitando dobles barras con `rstrip('/')`; si no hay `ASSETS_BASE_URL` configurada, devuelve la clave cruda; si la clave es `None`/vacía, devuelve `None` — relevante para `io_key`, que es nullable).
- **Librerías usadas**: `libs.core.responses.HandledError`/`generate_response`/`handle_exceptions`; `libs.orm.banks.Banks` (método `get_by_id`).
- **Decoradores**: solo `@handle_exceptions` (endpoint público, sin `require_auth`).

#### `get_banks`

- **Trigger**: `httpApi: { method: GET, path: /banks/get-banks }`.
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions`.
- **Flujo**: no recibe parámetros de entrada; llama a `Banks.get_all(active=True)` para obtener solo los bancos activos (ordenados por `tier` y `name`, según la implementación de `Banks.get_all`), y construye una lista con los campos públicos de cada uno (`id`, `code`, `name`, `logo_url` resuelto inline contra `ASSETS_BASE_URL`, `description`, `tier`, `rating_by`, `highlights`). A diferencia de `get_bank`, aquí la resolución de `logo_url` se hace inline con una expresión condicional en vez de la función `_asset_url` (duplicación menor de lógica entre handlers) y no se expone `io_url` (no aplica en un listado). Responde 200 con `{"banks": [...]}`.
- **Librerías usadas**: `libs.core.responses.generate_response`/`handle_exceptions`; `libs.orm.banks.Banks` (método `get_all`).
- **Decoradores**: solo `@handle_exceptions`.

#### `simulate`

- **Trigger**: `httpApi: { method: GET, path: /banks/simulate }`.
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions`.
- **Flujo**: lee `amount` y `term` de `queryStringParameters`. Convierte `amount` a `Decimal(str(amount))` (para preservar precisión decimal en el cálculo financiero); si la conversión falla o el resultado es `<= 0`, `HandledError("invalid_amount", 400)`. Convierte `term` a `int`; si falla o es `<= 0`, `HandledError("invalid_term", 400)`. Llama a `get_ranked_rates(amount, term)` (de `libs.utils.rates`), que devuelve una lista de tuplas `(bank_id, rate)` ya ordenada por mejor tasa, solo para los bancos cuyas bandas de monto y plazo cubren los valores pedidos. Construye el catálogo completo de bancos activos vía la función local `_get_banks_data()` (misma forma que `get_banks`, pero indexado por `bank.id` en un diccionario en vez de una lista). Para cada `(bank_id, rate)` rankeado que además esté en el catálogo de bancos activos, calcula `interest`/`final` con `yield_cop(amount, rate, term)` (interés compuesto EA sobre `term` días, base 365) y agrega `rate`, `interest`, `final` (convertidos a `float` para la respuesta JSON) al diccionario de ese banco, insertándolo en `banks_data_ranked` — preservando así el orden de ranking recibido de `get_ranked_rates` (los diccionarios en Python preservan orden de inserción). Responde 200 con `{"amount": float(amount), "term": term, "banks": banks_data_ranked}`. Nótese que si un banco tiene tasa rankeada pero no está activo (no aparece en `_get_banks_data`), se descarta silenciosamente del resultado (el `if bank_id in banks_data` filtra ese caso).
- **Librerías usadas**: `libs.core.responses.HandledError`/`generate_response`/`handle_exceptions`; `libs.orm.banks.Banks` (vía `_get_banks_data`); `libs.utils.rates.get_ranked_rates` y `libs.utils.rates.yield_cop`.
- **Decoradores**: solo `@handle_exceptions`.

### Clases y métodos de dominio propios del servicio

El servicio `banks` tampoco tiene una carpeta `domain/` ni una carpeta `utils/` propia bajo `services/banks/src/`. La única lógica no trivial de este servicio —resolución de URLs de assets (`_asset_url` en `get_bank`, lógica inline equivalente en `get_banks`/`simulate`) y el armado de `banks_data`/`banks_data_ranked` (`_get_banks_data` en `simulate`)— está definida como funciones privadas (prefijo `_`) dentro de cada `handler.py`, no en un módulo de dominio compartido dentro del servicio. El resto de las reglas de negocio (ranking de tasas, cálculo de rendimiento compuesto) vive en `backend/libs/utils/rates.py`, documentado en la sección de librerías compartidas.

---

## 3. Servicio `files`

### Propósito

El servicio `files` es el microservicio responsable de la gestión de archivos adjuntos de los procesos de crédito dentro de la plataforma CDTS. Su responsabilidad se reduce deliberadamente a dos operaciones: (1) emitir URLs prefirmadas de S3 para que el navegador del usuario suba un documento directamente al bucket privado, sin que el archivo pase por Lambda; y (2) registrar en la base de datos (tabla `files`) los metadatos de cada archivo efectivamente subido, reaccionando de forma asíncrona al evento `s3:ObjectCreated` del bucket. No expone un endpoint de descarga ni de borrado — solo subida y consulta de metadatos.

Las entidades de negocio que maneja son `Files` (una fila por archivo subido, con `process_id`, `file_type`, `s3_key`, `original_name`, `size_bytes`, `content_type`, `uploaded_at`) y, por relación, `Processes` (el proceso de crédito al que pertenece cada archivo; `files` solo lo lee para validar pertenencia, no lo administra). El catálogo de tipos de archivo soportados (`FileType`: `TAX_DECLARATION`, `RUT`, `BANK_CERT`, `INVESTMENT_ORDER`) define qué clase de documento de soporte se está subiendo. El servicio no implementa lógica de autorización de negocio propia más allá de verificar que el proceso pertenezca al usuario autenticado; la clasificación y validación de completitud de documentos (p. ej. qué archivos exige cada proceso) vive en el servicio `processes`, que invoca a `files` internamente (ver handler `list_process_files`).

### Arquitectura de despliegue

**`serverless.yml`**

- **Provider**: `runtime: python3.12`, `region` parametrizable por `${opt:region, 'us-east-1'}`, `stage` parametrizable por `${opt:stage, 'dev'}`, `stackName: cdts-${sls:stage}-files`, `memorySize: 512`, `timeout: 15` (segundos, default para todas las funciones salvo que su `function.yml` lo sobreescriba), `logRetentionInDays: 14`.
- **`httpApi`**: `cors: true` — habilita CORS automático de API Gateway HTTP API para todas las rutas del servicio, necesario porque `get_upload_url` es invocado directamente desde el navegador antes de que el frontend suba el archivo al bucket.
- **`environment`** (variables inyectadas a todas las Lambdas del servicio):
  - `STAGE: ${sls:stage}` — identifica el entorno de despliegue (dev/qa/prod, etc.).
  - `SSM_DB_PATH: /cdts/${sls:stage}/db` — ruta base en AWS SSM Parameter Store donde se leen las credenciales de conexión a la base de datos Postgres.
  - `FILES_BUCKET: cdts-${sls:stage}-files` — nombre del bucket S3 privado de archivos; es leído explícitamente por `get_upload_url/handler.py` vía `os.environ["FILES_BUCKET"]` para construir las URLs prefirmadas.
- **`iam.role.statements`** (permisos IAM del rol de ejecución de las Lambdas, con nombre fijo `cdts-${sls:stage}-files-lambda`):
  - `ssm:GetParametersByPath` sobre `arn:aws:ssm:*:*:parameter/cdts/${sls:stage}/db` y su subárbol — permite leer la configuración de conexión a la base de datos desde Parameter Store.
  - `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` sobre `arn:aws:s3:::cdts-${sls:stage}-files/*` — permite generar URLs prefirmadas de subida/descarga y que el worker `on_upload` llame a `HeadObject` (de hecho, `HeadObject` reutiliza permisos de lectura de objeto) sobre cualquier objeto del bucket.
- **`plugins`/`custom`**: usa el plugin `serverless-python-requirements`, configurado con `dockerizePip: false` (empaqueta las dependencias nativamente, sin contenedor Docker), `slim: false` (no elimina metadata/tests de los paquetes instalados) y `fileName: requirements.txt` (apunta explícitamente al archivo de dependencias del servicio).
- **`package.patterns`**: excluye todo por defecto (`'!**'`) y sólo reincluye `src/**` y `libs/**` (el código fuente propio y la copia local de las librerías compartidas), excluyendo explícitamente `__pycache__`, `*.pyc` y los archivos de test colocados junto a cada handler (`test.py`, `integration.py`, `conftest.py`) para que no viajen en el paquete de despliegue.
- **`resources`**: este es el servicio con la infraestructura más particular del backend, porque declara su propio bucket S3 vía CloudFormation:
  - `FilesBucket` (`AWS::S3::Bucket`), nombrado `cdts-${sls:stage}-files`, con bloqueo total de acceso público (`PublicAccessBlockConfiguration` con los cuatro flags en `true`), `ObjectOwnership: BucketOwnerEnforced` (desactiva ACLs, el dueño del bucket es dueño de todo objeto) y cifrado en reposo por defecto `AES256`. Define además una `CorsConfiguration` que permite `PUT`, `GET`, `HEAD` desde cualquier origen (`AllowedOrigins: ['*']`) con cualquier header, exponiendo el header `ETag` — esto es lo que hace posible que el navegador haga el `PUT` directo contra la URL prefirmada sin que el bucket rechace la petición por política CORS.
  - La parte más relevante: un bloque `NotificationConfiguration.LambdaConfigurations` que suscribe al bucket al evento `s3:ObjectCreated:*`, filtrado por prefijo de key `processes/` (`S3Key.Rules: Name: prefix, Value: processes/`), e invoca la función `OnUnderscoreuploadLambdaFunction` (el nombre lógico de CloudFormation generado automáticamente por Serverless Framework a partir del nombre de función `on_upload`, donde el guión bajo se traduce a `Underscore` en el identificador lógico). Esto es el disparador real del worker `on_upload`: no hay un bloque `events` en su `function.yml`, sino que la suscripción se declara a mano en `resources` porque Serverless Framework no soporta declarativamente notificaciones de S3 sobre un bucket que el propio stack está creando sin crear un ciclo de dependencia; por eso también existe el recurso explícito `OnUnderscoreuploadLambdaPermissionFilesBucketS3` (`AWS::Lambda::Permission`) que otorga a `s3.amazonaws.com` el permiso `lambda:InvokeFunction` sobre `OnUnderscoreuploadLambdaFunction`, y el bucket declara `DependsOn: [OnUnderscoreuploadLambdaPermissionFilesBucketS3]` para garantizar que el permiso exista antes de que CloudFormation intente crear la notificación.
  - El stack exporta un `Output` `FilesBucketName` con el nombre del bucket.

**`requirements.txt`**

- `sqlalchemy==2.0.34` — ORM y capa de acceso a datos (usado por `libs/orm/files.py` y `libs/orm/processes.py` para construir las sentencias `select`/`insert` sobre la tabla `files`).
- `pg8000==1.31.2` — driver Postgres puro-Python usado por SQLAlchemy para conectarse a la base de datos (no requiere compilar extensiones nativas como `psycopg2`, lo que simplifica el empaquetado sin Docker, coherente con `dockerizePip: false`).
- `scramp==1.4.17` — implementa el mecanismo de autenticación SCRAM (`SCRAM-SHA-256`) que Postgres exige por defecto; es una dependencia de `pg8000` para completar el handshake de autenticación contra la base de datos.

**Auto-registro de handlers**

El archivo `services/files/functions.js` hace dos cosas al ser evaluado por Serverless Framework: primero, sincroniza físicamente `backend/libs/` hacia `services/files/libs/` (borra `./libs` y copia de nuevo con `fs.cpSync`) para que el plugin de empaquetado incluya las librerías compartidas dentro del paquete de despliegue de este servicio (ese directorio `libs/` local está en `.gitignore`, es un artefacto de build); segundo, delega la construcción del mapa de funciones a `backend/utils/build-functions.js`, invocado como `require('../../utils/build-functions')(__dirname)`.

`build-functions.js` es compartido por todos los servicios del backend. Al ejecutarse recibe el `serviceDir` (la carpeta del servicio) y retorna una función asíncrona que Serverless Framework invoca con `{ options, resolveConfigurationProperty }`. El mecanismo es: para cada tipo de carpeta en `['handlers', 'scheduled', 'workers']`, si existe `src/<tipo>/`, enumera sus subcarpetas (ordenadas alfabéticamente). Cada subcarpeta debe llamarse en `snake_case` (se valida con la regex `^[a-z][a-z0-9_]*$`, y si no cumple lanza un error explicando que Python no puede importar carpetas con guiones) y debe contener obligatoriamente un `function.yml`; si falta, el build falla con un error explícito — en este servicio, por tanto, **no hay** ningún handler con trigger HTTP "por defecto": todas las carpetas (`get_upload_url`, `list_process_files`, `on_upload`) tienen su `function.yml` propio. El nombre lógico de la función se construye como `cdts-${stage}-${service}-${folderKebab}` (sustituyendo `_` por `-` en el nombre de carpeta) y el `handler` apuntando siempre a `src/<tipo>/<folder>/handler.handler`; ambos valores pueden ser sobreescritos si el `function.yml` del handler define explícitamente las claves `name`/`handler` (spread `...custom` al final, que gana sobre los valores calculados). Cualquier otra clave del `function.yml` (`events`, `description`, `timeout`, `layers`, `environment`, etc.) se mezcla tal cual en la definición de la función.

### Handlers

#### `get_upload_url` (`src/handlers/get_upload_url/`)

- **Trigger**: HTTP, `POST /files/upload-url` (declarado en `function.yml` vía `events: [{ httpApi: { method: POST, path: /files/upload-url } }]`).
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions` y `@require_auth` (en ese orden de aplicación, de afuera hacia adentro: `handle_exceptions` envuelve a `require_auth`).
- **Flujo**: Parsea el body JSON (`json.loads(event.get("body") or "{}")`) y extrae `process_id`, `file_type`, `content_type` (default `"application/pdf"`) y `original_name`. Primero valida presencia de `process_id` y `file_type` (400 `"process_id and file_type are required"` si faltan); luego que `file_type` esté en el conjunto `ALLOWED_TYPES` derivado del enum `FileType` (400 con el listado de valores permitidos); luego que `content_type` esté en el whitelist fijo `ALLOWED_CONTENT_TYPES` (`application/pdf`, `image/jpeg`, `image/png`) (400 `"content_type not allowed"`). Convierte `process_id` a `UUID`, capturando `TypeError`/`ValueError` para responder 400 `"invalid process_id"` si no es un UUID válido. Busca el proceso con `Processes.get_by_id(process_id)` y verifica que exista **y** que su `user_id` coincida con `event["user"].id` (el usuario inyectado por `require_auth`); si no, responde 404 `"process_not_found"` — esta es la única comprobación de autorización de negocio del handler: impide que un usuario autenticado solicite subir un archivo a un proceso que no es suyo. Genera un `file_id` nuevo (`uuid4()`), calcula la extensión del archivo (`_extension_for`: prioriza la extensión tomada de `original_name` si tiene un punto; si no, mapea el `content_type` a `.pdf`/`.jpg`/`.png`) y construye la key S3 determinística `processes/{process.id}/{file_type}/{file_id}{ext}` — este es exactamente el patrón de key que el worker `on_upload` espera parsear. Codifica el nombre original con `urllib.parse.quote` (porque los metadatos de S3 deben ser ASCII) y lo guarda en `metadata={"original-name": safe_name}`. Llama a `presign_upload(BUCKET, key, content_type, metadata=metadata)` para obtener la URL prefirmada de `PUT` y responde 200 con `upload_url`, `key`, `content_type`, `upload_headers` (incluyendo `x-amz-meta-original-name`, que el cliente debe reenviar exactamente igual al hacer el `PUT` o S3 rechaza la firma) y `expires_in: 900` (informativo; el TTL real de la URL lo define `presign_upload` con su propio default).
- **Librerías de `backend/libs/` usadas**: `libs.core.responses` (`HandledError`, `generate_response`, `handle_exceptions`) para las respuestas y manejo centralizado de errores/commit de transacción; `libs.core.s3.presign_upload` para generar la URL firmada; `libs.orm.files.FileType` solo como fuente del catálogo de tipos válidos (no se usa `Files` acá, solo se lee S3); `libs.orm.processes.Processes` para el lookup y validación de pertenencia del proceso; `libs.utils.auth.require_auth` para exigir sesión.
- **Decorador `@require_auth`**: lee el header `Authorization`, exige el esquema `Bearer <token>` (401 `missing_bearer_token` si falta o `invalid_or_expired_token` si el token está vacío), hashea el token (`SHA-256`) y lo busca en `BearerTokens`; si no existe, está revocado (`revoked_at` no nulo) o expiró (`is_alive`), responde 401 `invalid_or_expired_token`. Si es válido, resuelve el usuario (`Users.get_by_id`) y lo inyecta en `event["user"]` y `event["token"]` antes de delegar al handler real.
- **Decorador `@handle_exceptions`**: envuelve la ejecución en `try/except`; si todo sale bien hace `db_session.commit()` y retorna la respuesta; si se lanza un `HandledError` hace `rollback()`, loggea en nivel `WARNING` y devuelve `generate_response({"error": e.message}, e.status_code)`; cualquier otra excepción hace `rollback()`, loggea `ERROR` con traceback y devuelve 500 `internal_server_error`; en el `finally` siempre cierra la sesión (`db_session.close()`) porque es un singleton a nivel de módulo que sobrevive entre invocaciones en un contenedor "warm", y dejarla abierta haría que invocaciones posteriores sigan leyendo el mismo snapshot de transacción.

#### `list_process_files` (`src/handlers/list_process_files/`)

- **Trigger**: ninguno declarado en `function.yml` (sólo tiene `description`, sin bloque `events`). Según el mecanismo de `build-functions.js`, al no haber clave `events` en el `function.yml` esta Lambda queda registrada en el stack sin ningún event source — es decir, no es invocable por HTTP ni por ningún trigger de AWS; sólo puede invocarse mediante `lambda:InvokeFunction` directo (IAM invoke), tal como documenta el propio comentario del `function.yml`: "Invoked directly by `processes.get_required_files`; no HTTP event -- IAM invoke only".
- **Firma**: `handler(event, context)`, decorado únicamente con `@handle_exceptions` (sin autenticación: no es un endpoint HTTP expuesto al usuario final, sino una llamada interna de servicio a servicio donde la invocación entre Lambdas ya está controlada por IAM).
- **Flujo**: lee `process_id` directamente de `event.get("process_id")` (no de un body HTTP, porque el `event` acá es el payload crudo que pasa el invocador vía `boto3`/SDK), llama a `Files.list_by_process(process_id)` y proyecta cada fila a un diccionario con `id`, `file_type`, `original_name`, `uploaded_at`. Responde 200 con `{"files": [...]}`. No valida que `process_id` sea un UUID válido ni que exista — confía en que el servicio invocador (`processes`) ya hizo esa validación.
- **Librerías usadas**: `libs.core.responses` (`generate_response`, `handle_exceptions`); `libs.orm.files.Files`, concretamente su método de clase `list_by_process(process_id)`, que ejecuta un `SELECT` ordenado por `uploaded_at DESC`.

#### `on_upload` (`src/workers/on_upload/`)

- **Trigger**: evento S3 `ObjectCreated:*` del bucket `FilesBucket`, filtrado por prefijo `processes/`. Como se explicó en la sección de `resources`, este trigger **no** se declara con un bloque `events:` en el `function.yml` del worker (de hecho el `function.yml` sólo define `description` y `timeout: 30`, sobreescribiendo el timeout default de 15s del provider porque el `HeadObject` + escritura en base de datos puede tardar algo más); la suscripción real vive en el `NotificationConfiguration` de CloudFormation en `serverless.yml`.
- **Firma**: `handler(event, context)`, **sin** decoradores (no usa `@handle_exceptions` ni `@require_auth`, porque no es HTTP: no hay "respuesta" semántica que el API Gateway espere, y el manejo de errores aquí es deliberadamente por-registro, no por-invocación completa).
- **Forma del evento recibido**: un evento S3 estándar de Lambda, con la forma `{"Records": [{"s3": {"bucket": {"name": ...}, "object": {"key": ...}}}, ...]}`. Puede traer **múltiples** records en una sola invocación (S3 puede agrupar notificaciones).
- **Flujo**: itera sobre `event.get("Records", [])`, y para cada uno llama a `_process_record(record)` dentro de un `try/except` individual — si un record falla, se loggea el error (`Logger.log("ERROR", ...)`) y se continúa con el siguiente, en vez de abortar toda la invocación; esto es importante porque S3 reintentaría toda la invocación si lanzara una excepción no capturada, lo que duplicaría el procesamiento de los records que sí tuvieron éxito. Al final hace un único `db_session.commit()` para todos los records procesados con éxito en esa invocación, y retorna `{"processed": <cantidad de records>}` (valor informativo, S3 no lo interpreta). `_process_record` decodifica la key (`unquote_plus`, porque S3 codifica espacios como `+` y otros caracteres especiales en el nombre de la key del evento), la parte en segmentos por `/` y valida que tenga al menos 4 partes y que la primera sea literalmente `"processes"` (si no, loggea `WARNING` y descarta silenciosamente el record — protección contra objetos subidos fuera del patrón esperado, aunque el filtro de prefijo de S3 ya debería garantizar el prefijo `processes/`). Extrae `process_id_raw`, `file_type` y reconstruye `filename` uniendo el resto de segmentos (por si el nombre de archivo contuviera `/`, aunque en la práctica `get_upload_url` siempre genera un nombre plano `{uuid}{ext}`). Convierte `process_id_raw` a `UUID`, descartando el record con `WARNING` si no es válido. Llama a `head_object(bucket, key)` para obtener `ContentLength`, `ContentType` y los `Metadata` del objeto recién subido, y recupera de ahí `original-name` (si está presente, lo decodifica con `unquote`; si no, usa el `filename` extraído de la key como fallback). Finalmente llama a `Files.create(process_id=..., file_type=..., s3_key=key, original_name=..., size_bytes=..., content_type=...)` y loggea `INFO` confirmando el registro. El comentario de cabecera del archivo documenta explícitamente la garantía de idempotencia: como `s3_key` es `UNIQUE` a nivel de base de datos, una entrega duplicada del mismo evento (S3 sólo garantiza *at-least-once*) hace fallar el `INSERT` con una excepción de integridad, que es capturada por el `try/except` por-record del `handler` y simplemente logueada, sin crear una segunda fila.
- **Librerías usadas**: `libs.core.db.db_session` (para el `commit()` final); `libs.core.logger.Logger` (logging estructurado); `libs.core.s3.head_object` (lectura de metadatos del objeto recién creado); `libs.orm.files.Files`, método `create`.

### Clases y métodos de dominio propios del servicio

El servicio `files` **no** tiene una carpeta `domain/` ni una carpeta `utils/` local (distinta de `backend/libs/`). Toda la lógica de acceso a datos, autenticación y utilidades vive en las librerías compartidas (`backend/libs/orm/files.py`, `backend/libs/orm/processes.py`, `backend/libs/core/s3.py`, `backend/libs/utils/auth.py`), documentadas en la sección correspondiente de librerías compartidas. La única lógica estrictamente local al servicio es la función auxiliar `_extension_for(content_type, original_name)` dentro de `get_upload_url/handler.py`, que resuelve la extensión de archivo a partir del nombre original o, en su defecto, de un mapeo fijo de `content_type` a extensión (`application/pdf -> .pdf`, `image/jpeg -> .jpg`, `image/png -> .png`, u `""` si el `content_type` no está en el mapa).

---

## 4. Servicio `forms`

### Propósito

El servicio `forms` administra el formulario de datos personales, financieros y de identificación que cada usuario debe completar como parte del proceso de originación de crédito (datos de identidad, nacimiento, documento, contacto, estado civil, nivel educativo, condición de PEP —persona expuesta políticamente—, e información financiera básica como ingresos, egresos, activos, pasivos y si es declarante de renta). A diferencia de `files`, aquí no hay una relación uno-a-muchos con un proceso: la entidad `Forms` tiene una relación **uno a uno** con el usuario (`user_id` es la primary key de la tabla `forms`), es decir, cada usuario tiene como máximo un formulario, que se crea o actualiza (upsert) cada vez que lo diligencia.

El servicio también expone un catálogo de referencia geográfica (`get_locations`) usado para poblar los selectores de ubicación del formulario (departamentos/ciudades/localidades de Colombia y el listado de países), separado de la lógica de upsert porque es información estática que no requiere autenticación y es cacheable. En conjunto, `forms` maneja dos entidades/catálogos: `Forms` (el formulario del usuario) y los catálogos estáticos de `ColombianLocations`/`Countries` (datos de referencia, no tablas de base de datos).

### Arquitectura de despliegue

**`serverless.yml`**

- **Provider**: idéntico en forma al de `files` — `runtime: python3.12`, `region`/`stage` parametrizables, `stackName: cdts-${sls:stage}-forms`, `memorySize: 512`, `timeout: 15`, `logRetentionInDays: 14`.
- **`httpApi`**: `cors: true`, habilitando CORS para que el frontend consuma directamente `/forms/*` desde el navegador.
- **`environment`**:
  - `STAGE: ${sls:stage}` — mismo propósito que en `files`, identificar el entorno.
  - `SSM_DB_PATH: /cdts/${sls:stage}/db` — ruta en SSM Parameter Store para la configuración de conexión a Postgres.
  - A diferencia de `files`, **no** hay variable `FILES_BUCKET` ni ninguna otra relacionada con S3, porque `forms` no interactúa con almacenamiento de objetos — toda su persistencia es relacional.
- **`iam.role.statements`** (rol `cdts-${sls:stage}-forms-lambda`): únicamente `ssm:GetParametersByPath` sobre `arn:aws:ssm:*:*:parameter/cdts/${sls:stage}/db` (y subárbol), para leer las credenciales de base de datos. No hay ningún statement de S3, SQS ni de ningún otro servicio AWS — el permiso IAM de este servicio es el mínimo posible, coherente con que sólo necesita hablar con Postgres.
- **`plugins`/`custom`**: mismo plugin `serverless-python-requirements` con idéntica configuración que `files` (`dockerizePip: false`, `slim: false`, `fileName: requirements.txt`).
- **`package.patterns`**: idénticos a `files` — incluye sólo `src/**` y `libs/**`, excluye `__pycache__`, `*.pyc` y los archivos de test colocados junto a cada handler.
- **`resources`**: `forms` **no** declara ningún bloque `resources` en su `serverless.yml` — no crea tablas, buckets, colas ni ningún otro recurso de AWS propio. La tabla `forms` en Postgres se asume gestionada por una migración/esquema compartido fuera de este stack de Serverless (no por CloudFormation de este servicio).

**`requirements.txt`**

Idéntico al de `files`: `sqlalchemy==2.0.34` (ORM, usado por `libs/orm/forms.py` para las sentencias `select`/`insert ... on_conflict_do_update`), `pg8000==1.31.2` (driver Postgres puro-Python) y `scramp==1.4.17` (mecanismo de autenticación SCRAM-SHA-256 requerido por `pg8000` para autenticar contra Postgres).

**Auto-registro de handlers**

El `functions.js` de `forms` es textualmente idéntico al de `files`: primero sincroniza `backend/libs/` hacia `services/forms/libs/` (borrando y copiando de nuevo, directorio gitignoreado) para que el paquete de despliegue incluya las librerías compartidas, y luego delega en el mismo `backend/utils/build-functions.js` (ver explicación completa del mecanismo en la sección del servicio `files`: escaneo de `src/handlers`/`src/scheduled`/`src/workers`, exigencia de `snake_case` y de un `function.yml` por carpeta, construcción de `name: cdts-${stage}-forms-${folderKebab}` y `handler: src/handlers/<folder>/handler.handler`, con posibilidad de que el `function.yml` sobreescriba `name`/`handler`/agregue `events` u otras claves). `forms` sólo tiene carpeta `src/handlers/` (no tiene `src/workers/` ni `src/scheduled/`), con tres handlers: `get_form`, `get_locations` y `upsert_form`, los tres con `function.yml` propio y evento HTTP explícito.

### Handlers

#### `get_form` (`src/handlers/get_form/`)

- **Trigger**: HTTP, `GET /forms/get-form`.
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions` y `@require_auth`.
- **Flujo**: obtiene el usuario autenticado desde `event.get("user")` (inyectado por `require_auth`) y busca su formulario con `Forms.get_by_user_id(user.id)`. Si no existe fila, responde 200 con `{"form": null}` (es decir, "el usuario aún no ha diligenciado el formulario" es un estado válido, no un error). Si existe, serializa **todos** los campos del formulario (nombre, segundo nombre, apellidos, género, fecha de nacimiento, país/departamento/ciudad de nacimiento, nacionalidad, email, tipo/número de documento, fecha y lugar de expedición del documento, extensión/número de teléfono, estado civil, nivel educativo, si es PEP, ingresos/egresos mensuales, activos/pasivos totales, si es declarante de renta, y `updated_at`), formateando `birth_date` y `document_issuance_date` como cadenas `dd/mm/yyyy` (`strftime("%d/%m/%Y")`) para consumo directo del frontend. No hace ninguna otra validación: es un endpoint de sólo lectura.
- **Librerías usadas**: `libs.core.responses` (`generate_response`, `handle_exceptions`); `libs.orm.forms.Forms` (sólo `get_by_user_id`); `libs.utils.auth.require_auth`.
- **Decorador `@require_auth`**: igual que en `files` (ver explicación detallada arriba) — exige `Authorization: Bearer <token>` válido, no revocado y no expirado, e inyecta `event["user"]`/`event["token"]`.

#### `get_locations` (`src/handlers/get_locations/`)

- **Trigger**: HTTP, `GET /forms/get-locations`.
- **Firma**: `handler(event, context)`, decorado **sólo** con `@handle_exceptions` — es el único handler de `forms` que **no** requiere autenticación, porque sirve un catálogo estático público (no hay dato sensible ni dependiente de usuario).
- **Flujo**: lee el query string param `type` desde `event.get("queryStringParameters")`. Define localmente una clase `LocationType` como enum informal de dos valores válidos: `colombian_locations` y `countries`. Si `type == "colombian_locations"`, llama a `handle_colombian_locations()` (función local del propio `handler.py`, no de `libs/`): reconstruye un diccionario anidado departamento → `{label, cities: {ciudad → {label, localities?}}}` a partir de `ColombianLocations._load_data()`, exponiendo etiquetas legibles (`label`) en cada nivel y las localidades anidadas sólo cuando existen (`city_info.get("localities")`). Si `type == "countries"`, llama a `handle_countries()`, que delega directamente en `Countries.get_countries_map()`. Si `type` no es ninguno de los dos valores esperados (o falta), lanza `HandledError` 400 con el mensaje explicando los valores aceptados. La respuesta exitosa (200) envía `{"data": ...}` junto con el header `Cache-Control: public, max-age=7200` (2 horas) — refuerza que este catálogo es estático y cacheable en el borde/CDN o por el navegador.
- **Librerías usadas**: `libs.core.responses` (`HandledError`, `generate_response`, `handle_exceptions`); `libs.utils.locations.ColombianLocations` y `libs.utils.locations.Countries`, usando específicamente los métodos de clase `_load_data()` (acceso directo al dato crudo cacheado, en vez de usar los helpers públicos de más alto nivel de esas clases) y `get_countries_map()`.

#### `upsert_form` (`src/handlers/upsert_form/`)

- **Trigger**: HTTP, `PUT /forms/upsert-form`.
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions` y `@require_auth`. Es, con diferencia, el handler con más lógica de validación de todo el conjunto documentado aquí: define seis funciones auxiliares privadas de módulo (`_string`, `_enum`, `_date`, `_bool`, `_float`, `_country`, `_location`) que implementan un mini-framework de validación de campos sobre el `body` recibido.
- **Flujo paso a paso**: parsea el body JSON y toma el `user` inyectado por `require_auth`. Valida y normaliza, en orden:
  - `name`, `last_name` (string requerido, convertido a mayúsculas vía `_string(..., uppercase=True)`), `second_name`, `second_last_name` (igual pero opcionales).
  - `document_number`: requerido (400 si falta), forzado a `str`, recortado, y debe ser enteramente numérico (`str.isdigit()`, 400 `"document_number must be numeric"` si no).
  - `document_type`: requerido, debe pertenecer al enum `DocumentType` (`CC`, `CE`, `TI`, `PA`), 400 con el listado de valores si no es válido.
  - `email`: requerido, validado contra una regex local `_EMAIL_RE` (no usa un validador de librería), normalizado a minúsculas y sin espacios; 400 `"email is not valid"` si no matchea.
  - `gender` (`_enum` contra `GenderType`), `birth_date` (`_date`, parsea ISO `YYYY-MM-DD` con `date.fromisoformat` y lo convierte a `datetime` con `tzinfo=timezone.utc`; 400 si el formato es inválido), `birth_country/department/city` (`_location(body, "birth", Location)`), `nationality` (`_country`), `document_issuance_date` (`_date`), `document_issuance_country/department/city` (`_location(body, "document_issuance", IssuanceLocation)` — nótese que usa una subclase distinta, `IssuanceLocation`, con reglas de validación de ciudad distintas a las de nacimiento), `phone_ext`/`phone_number` (strings requeridos), `civil_status` (`_enum` contra `CivilStatusType`), `education_level` (`_enum` contra `EducationLevelType`), `is_pep` (`_bool`), `monthly_income`/`monthly_expenses`/`total_assets`/`total_liabilities` (`_float`, exige número ≥ 0), `is_tax_declarant` (`_bool`).
  - Con todos los campos validados, llama a `Forms.upsert(user.id, **todos_los_campos)` y re-serializa la fila resultante con el mismo formato de salida que usa `get_form` (incluyendo el formateo `dd/mm/yyyy` de las dos fechas), devolviendo 200 con `{"form": {...}}`.
  - Las funciones auxiliares encapsulan el patrón repetido "si falta y es requerido, 400; si viene, validar tipo/forma, 400 si no cumple": `_string` valida no-vacío y aplica `.strip()`/`.upper()` opcional; `_enum` valida pertenencia a un `Enum` de SQLAlchemy/Python; `_date` parsea y convierte a `datetime` aware; `_bool` exige `isinstance(value, bool)` estricto (rechaza `"true"`/`1` como substitutos); `_float` castea y exige no-negatividad; `_country` reutiliza `_string` y además valida contra el catálogo `Countries.get_country`; `_location` combina tres `_string` (país/departamento/ciudad) y, sólo si el país es Colombia y hay departamento o ciudad informados, valida la combinación contra el catálogo (`location_cls(country, department, city).city_label is None` → 400 "no es válido").
- **Librerías usadas**: `libs.core.responses` (`HandledError`, `generate_response`, `handle_exceptions`); `libs.orm.forms` (`CivilStatusType`, `DocumentType`, `EducationLevelType`, `Forms`, `GenderType`) — usa el método `Forms.upsert`, que internamente ejecuta un `INSERT ... ON CONFLICT (user_id) DO UPDATE` (upsert nativo de Postgres vía SQLAlchemy); `libs.utils.auth.require_auth`; `libs.utils.locations` (`Countries`, `IssuanceLocation`, `Location`) para la validación geográfica.
- **Decorador `@require_auth`**: mismo mecanismo descrito en `files`/`get_form`.

### Clases y métodos de dominio propios del servicio

Igual que `files`, el servicio `forms` **no** tiene una carpeta `domain/` ni `utils/` local separada de `backend/libs/`; no existen `services/forms/domain/` ni `services/forms/utils/` en el árbol de archivos. Toda la lógica de catálogos (`ColombianLocations`, `Countries`, `Location`, `IssuanceLocation`) y de persistencia (`Forms` y sus enums `DocumentType`, `GenderType`, `CivilStatusType`, `EducationLevelType`) vive en `backend/libs/`, documentada en la sección de librerías compartidas.

Lo que sí es exclusivamente local a cada handler de este servicio (definido directamente en el `handler.py`, no reutilizado entre handlers) es:

- En `get_locations/handler.py`: la clase `LocationType` (constantes `COLOMBIAN_LOCATIONS = "colombian_locations"`, `COUNTRIES = "countries"`) y las funciones `handle_colombian_locations() -> dict` y `handle_countries() -> dict`, que son simples transformadores de forma del dato crudo de los catálogos compartidos al formato de respuesta HTTP esperado por el frontend (no implementan ninguna regla de negocio nueva, sólo reestructuran diccionarios).
- En `upsert_form/handler.py`: las seis funciones de validación de campo (`_string`, `_enum`, `_date`, `_bool`, `_float`, `_country`, `_location`) descritas arriba, y la constante de módulo `_EMAIL_RE` (regex de validación de correo). Son funciones privadas (prefijo `_`) de uso exclusivo dentro de este handler; no se importan desde ningún otro módulo del servicio.

---

## 5. Servicio `processes`

### Propósito

El servicio `processes` administra el ciclo de vida de una "apertura de CDT" (Certificado de Depósito a Término) iniciada por un usuario: desde la creación del proceso con un banco, monto, plazo y tasa concretos, hasta la generación automática del documento de orden de inversión y la apertura de su ceremonia de firma. La entidad de negocio central es `Processes` (tabla `processes`), modelada en `libs/orm/processes.py` con una máquina de estados explícita (`ProcessStage`: `FORM → DOCUMENTS → SIGNATURE → PAYMENT → REVIEW → SENT_TO_BANK → COMPLETED`), de la cual este servicio solo opera los tres primeros tramos (`FORM`, `DOCUMENTS`, `SIGNATURE`); el resto de la máquina de estados pertenece a otros servicios no cubiertos aquí.

El servicio no es autosuficiente: delega en otros bloques del backend para completar cada paso -- invoca `banks` para simular la tasa real antes de confiar en lo que envía el cliente, `forms` para obtener el formulario de datos personales del usuario ya validado, `files` para saber qué documentos de soporte subió el usuario, y `signatures` para abrir la ceremonia de firma del documento generado. Este patrón de invocación Lambda-a-Lambda (sin pasar por API Gateway) es el mecanismo arquitectónico más relevante del servicio y se documenta en detalle en la sección de Handlers y en `libs/utils/lambda_invoke.py`. El nombre histórico de los endpoints (`create`, `get`, `advance`, `signature_callback`, `list_mine`) fue reemplazado en una refactorización reciente; hoy los handlers vigentes son `create_process`, `get_processes`, `get_required_files` y `set_process_form`, más el worker interno `generate_sign`.

### Arquitectura de despliegue

**`serverless.yml`**

- **`provider`**: runtime `python3.12`, `region` parametrizable por `${opt:region, 'us-east-1'}`, `stage` parametrizable por `${opt:stage, 'dev'}`, `stackName: cdts-${sls:stage}-processes`. `memorySize: 512` y `timeout: 15` son los valores por defecto para todas las funciones del servicio (el worker `generate_sign` los sobreescribe, ver más abajo). `logRetentionInDays: 14` fija la retención de los log groups de CloudWatch en dos semanas.
- **`httpApi`**: `cors: true` -- habilita CORS genérico (todos los orígenes/headers/métodos) en la API HTTP de API Gateway para todas las rutas del servicio.
- **`environment`** (variables inyectadas a todas las Lambdas del servicio):
  - `STAGE: ${sls:stage}` -- el stage activo; lo usa `libs/core/db.py` para fijar el `search_path` de Postgres (`SET search_path TO {STAGE}, pg_catalog`) y como fallback de `SSM_DB_PATH`, y lo usa `libs/utils/lambda_invoke.py` (`resolve_function_name`) para construir el nombre convencional de la Lambda destino en cada invocación cruzada.
  - `SERVICE: processes` -- el nombre del propio servicio; `lambda_invoke.resolve_function_name` lo usa como `service` por defecto cuando una invocación no pasa el parámetro `service` explícito (caso de uso: un handler invocando a un hermano del mismo bloque, p. ej. `get_required_files` invocando `generate_sign` sin especificar `service="processes"`).
  - `SSM_DB_PATH: /cdts/${sls:stage}/db` -- la ruta en SSM Parameter Store donde están las credenciales de la base de datos (`user`, `password`, `host`, `port`, `name` como parámetros `SecureString` bajo este path); `libs/core/db.py` la lee en frío con `ssm:GetParametersByPath` para construir la cadena de conexión `postgresql+pg8000://...`.
- **`iam.role.statements`** (rol dedicado `cdts-${sls:stage}-processes-lambda`):
  - `ssm:GetParametersByPath` + `ssm:GetParameter` sobre `arn:aws:ssm:*:*:parameter/cdts/${sls:stage}/db` y su subárbol `/*` -- necesarios para que `libs/core/db.py` pueda leer las credenciales de base de datos descritas arriba.
  - `kms:Decrypt` sobre `Resource: '*'` -- el comentario del propio `serverless.yml` aclara que los parámetros SSM anteriores son `SecureString` (cifrados con KMS) y que SSM los descifra al leerlos "pero solo si podemos invocar Decrypt"; el `Resource: '*'` es necesario porque SSM resuelve el descifrado contra la key administrada de forma transparente, y el scoping real de qué se puede leer ya lo impone el `Resource` acotado de los statements de `ssm:GetParameter`.
  - `lambda:InvokeFunction` sobre cinco ARNs explícitos, cada uno documentado con un comentario en el propio yml que indica qué handler de este servicio lo usa y por qué:
    - `cdts-${sls:stage}-banks-simulate` -- `create_process` corrobora `(amount, term)` contra las bandas de tasa vigentes invocando `banks.simulate` directamente en vez de confiar en una tasa enviada por el cliente.
    - `cdts-${sls:stage}-forms-get-form` -- `set_process_form` obtiene el formulario del usuario invocando `forms.get_form` directamente en lugar de duplicar esa consulta.
    - `cdts-${sls:stage}-files-list-process-files` -- `get_required_files` obtiene los archivos subidos del proceso invocando la Lambda interna `files.list_process_files`.
    - `cdts-${sls:stage}-processes-generate-sign` -- `get_required_files` dispara (de forma asíncrona) el propio worker interno `generate_sign` de este bloque una vez que todos los archivos requeridos están presentes.
    - `cdts-${sls:stage}-banks-get-bank` -- `generate_sign` obtiene la URL de la plantilla de orden de inversión del banco invocando `banks.get_bank` directamente.
    - `cdts-${sls:stage}-signatures-create-signature` -- `generate_sign` abre la ceremonia de firma del documento ya poblado invocando `signatures.create_signature`.
- **`plugins`**: `serverless-python-requirements`, que empaqueta las dependencias Python listadas en `requirements.txt` junto con el código.
- **`custom.pythonRequirements`**: `dockerizePip: false` (instala las dependencias con el Python local, sin levantar un contenedor Docker), `slim: false` (no recorta artefactos de las librerías empaquetadas) y `fileName: requirements.txt` (apunta explícitamente al archivo de dependencias de este servicio).
- **`package.patterns`**: arranca excluyendo todo (`'!**'`) y vuelve a incluir solo `src/**` (los handlers/workers), `libs/**` (la copia local de las librerías compartidas, ver mecanismo de `functions.js` más abajo) y `utils/**` (los helpers propios del bloque, es decir `services/processes/utils/`). Luego excluye explícitamente `__pycache__/**`, `*.pyc`, y los archivos de test colocados junto a cada handler (`test.py`, `integration.py`, `conftest.py`), que existen en el repo para que `pytest` los descubra en desarrollo pero nunca viajan dentro del paquete desplegado a Lambda.
- **`resources`**: este `serverless.yml` no define un bloque `resources` (CloudFormation) propio; no se crean aquí tablas, colas ni buckets -- la tabla `processes` se gestiona por fuera de este stack (migraciones de base de datos), y el servicio solo consume infraestructura ya existente (SSM, otras Lambdas) a través de IAM.
- **`functions: ${file(./functions.js):build}`** -- la lista de funciones no se escribe a mano; se delega a `functions.js`.

**Autoregistro de handlers (`functions.js` + `backend/utils/build-functions.js`)**

`services/processes/functions.js` hace dos cosas antes de delegar: (1) resuelve `backend/libs` (ruta relativa `../../libs` desde el directorio del servicio) y, si existe, borra y copia recursivamente su contenido a `services/processes/libs/` -- esta carpeta `libs/` local está en `.gitignore` y es la que efectivamente empaqueta `serverless-python-requirements`/`package.patterns` (`libs/**`), de modo que cada servicio despliega su propia copia congelada de las librerías compartidas en el momento del `sls deploy`/`sls package`. (2) Exporta `module.exports.build = require('../../utils/build-functions')(__dirname)`, que es el motor común a todos los bloques del backend.

`backend/utils/build-functions.js` recibe el directorio del servicio y devuelve una función async (la que Serverless Framework invoca al resolver `${file(./functions.js):build}`, con acceso a `options` y `resolveConfigurationProperty`). El algoritmo:
1. Resuelve `service` (del propio `serverless.yml`, aquí `processes`) y `stage` (de `--stage`/`-s`, default `'dev'`).
2. Recorre tres subcarpetas posibles bajo `src/`: `handlers`, `scheduled` y `workers` (en ese orden fijo, `TYPES`). Si una no existe, se omite sin error.
3. Para cada carpeta hija (orden alfabético, `fs.readdirSync(...).sort()`) exige que su nombre sea `snake_case` (regex `^[a-z][a-z0-9_]*$`; lanza error si no, porque Python no puede importar carpetas con guiones) y exige que exista un `function.yml` junto al `handler.py` -- si falta, lanza error de build (`Missing function.yml in ...`).
4. Carga ese `function.yml` con `js-yaml` y construye la entrada de la función como `{ name: cdts-{stage}-{service}-{folder-con-guiones}, handler: src/{type}/{folder}/handler.handler, ...custom }`, donde `custom` es el contenido parseado del `function.yml` y se aplica por *spread* **después** de `name`/`handler`, de modo que cualquier `name` o `handler` explícito dentro de ese `function.yml` gana por sobre la convención (escape hatch de último recurso). Todo lo demás que traiga el `function.yml` (`events`, `layers`, `timeout`, `memorySize`, `environment`, etc.) se agrega tal cual a la definición de la función.

En este servicio, ningún `function.yml` sobreescribe `name` ni `handler`; todos se limitan a declarar `description` y `events` (los cuatro handlers HTTP) o solo ajustes de recursos sin `events` (el worker). Por eso los cuatro handlers HTTP terminan nombrados `cdts-{stage}-processes-create-process`, `cdts-{stage}-processes-get-processes`, `cdts-{stage}-processes-get-required-files` y `cdts-{stage}-processes-set-process-form`, y el worker `cdts-{stage}-processes-generate-sign` -- exactamente los nombres que aparecen citados en los ARNs del bloque IAM. Si una carpeta de handler no incluyera el evento `httpApi` en su `function.yml` (no es el caso de ninguno aquí), de todos modos recibiría *algún* trigger HTTP por convención, pero `build-functions.js` no impone ese trigger por defecto por folder -- cada `function.yml` de este servicio declara explícitamente su propio `httpApi: { method, path }`.

**`requirements.txt`**

- `sqlalchemy==2.0.34` -- ORM y motor de queries; todas las clases de dominio (`Processes`, `Files`, etc. en `libs/orm/`) heredan de `Base` (`sqlalchemy.orm`) y las consultas (`select`, `insert`, `update`) se ejecutan a través del `db_session` singleton.
- `pg8000==1.31.2` -- driver puro-Python de PostgreSQL; es el dialecto (`postgresql+pg8000://...`) con el que `libs/core/db.py` construye el `create_engine`.
- `scramp==1.4.17` -- implementa el mecanismo de autenticación SCRAM que `pg8000` necesita para negociar la autenticación contra Postgres; se declara explícitamente porque `serverless-python-requirements` empaqueta dependencias de forma estática (sin resolución dinámica en el contenedor Lambda).
- `requests==2.32.3` -- cliente HTTP; el propio `requirements.txt` lo anota con el comentario `# generate_sign: downloads the bank's io_key template and populates it.` -- usado en `_fetch_template()` del worker para descargar la plantilla PDF del banco desde su `io_url`.
- `pypdf==5.1.0` -- lectura/escritura de PDF (`PdfReader`, `PdfWriter`); usado en `utils/investment_order.py` para fusionar (`merge_page`) la capa de texto generada con la plantilla del banco y producir el PDF final.
- `reportlab==4.2.5` -- generación de PDF desde cero (`pdfgen.canvas.Canvas`); usado en `utils/investment_order.py` para dibujar la capa de texto (datos del formulario, montos, checkboxes) que luego se fusiona sobre la plantilla.

### Handlers

#### `create_process` (`src/handlers/create_process/`)

- **Trigger**: `function.yml` declara `httpApi: { method: POST, path: /processes/create-process }`. Descripción: "Creates a CDT opening process in stage 'form'."
- **Firma**: `handler(event, context)`, decorado `@handle_exceptions` y `@require_auth` (de afuera hacia adentro: `require_auth` se ejecuta primero).
- **Flujo**:
  1. `require_auth` valida el header `Authorization: Bearer <token>`; si falta o no empieza con `"bearer "`, lanza `HandledError("missing_bearer_token", 401)`. Hashea el token (SHA-256) y busca `BearerTokens.get_by_hash`; si no existe, está revocado (`revoked_at is not None`) o expiró (`is_alive(bearer)` da falso), lanza `HandledError("invalid_or_expired_token", 401)`. Carga el `Users` asociado y, si existe, inyecta `event["user"]` y `event["token"]` antes de delegar al handler real.
  2. El handler toma `user = event.get("user")` y parsea el body JSON (`json.loads(event.get("body") or "{}")`).
  3. Extrae `bank_id`, `amount`, `term`; si falta cualquiera, `HandledError("Missing required fields", 400)`.
  4. Invoca de forma **síncrona** a `banks.simulate` vía `invoke_sync(function_key="simulate", payload={"queryStringParameters": {"amount": str(amount), "term": str(term)}}, service="banks")`, construyendo el payload como si fuera un evento HTTP de API Gateway (con `queryStringParameters`) aunque la invocación sea directa Lambda-a-Lambda. Si falla la invocación misma (`LambdaInvokeError`), responde `HandledError("simulation_unavailable", 502)`.
  5. Si la respuesta de `banks.simulate` no es `statusCode == 200`, propaga el mensaje de error recibido (`error_message`) y el código de estado original del simulador.
  6. Busca dentro de `simulation_result["banks"]` la entrada correspondiente a `str(bank_id)`; si el banco no aparece (no competitivo para ese monto/plazo), `HandledError("Bank not available for the given amount and term", 400)`.
  7. Crea el proceso con `Processes.create(user_id=user.id, bank_id=bank_id, amount=Decimal(str(amount)), term=int(term), rate=Decimal(str(simulation["rate"])))` -- nótese que la tasa (`rate`) persistida **no** proviene del cliente sino de la respuesta de `banks.simulate`, que es exactamente la validación server-side que motiva el permiso IAM `lambda:InvokeFunction` sobre `banks-simulate`. `Processes.create` inserta con `stage=ProcessStage.FORM.value`.
  8. Devuelve `generate_response({id, bank_id, amount, term, rate, stage, created_at}, 200)`.
  9. `@handle_exceptions` envuelve todo: si la función retorna normalmente, hace `db_session.commit()`; si se lanza `HandledError`, hace `rollback()`, loguea `WARNING` y devuelve `generate_response({"error": e.message}, e.status_code)`; cualquier otra excepción hace `rollback()`, loguea `ERROR` con traceback y devuelve 500 genérico (`internal_server_error`); en el `finally` siempre cierra la sesión (comentario explica que, en un contenedor "warm", la sesión es un singleton a nivel de módulo que sobrevive entre invocaciones, por lo que si no se cierra la transacción queda abierta y la siguiente invocación seguiría leyendo el mismo snapshot).
- **Librerías de `libs/` usadas**: `HandledError`, `generate_response`, `handle_exceptions` (`libs.core.responses`); `Banks` (`libs.orm.banks`); `Processes` (`libs.orm.processes`); `require_auth` (`libs.utils.auth`); `LambdaInvokeError`, `invoke_sync` (`libs.utils.lambda_invoke`).
- **Detalle notable**: el handler importa `Banks` de `libs.orm.banks` pero nunca la referencia en el cuerpo de la función -- es un import muerto, probablemente remanente de una versión anterior (antes del rename `create`→`create_process`) en la que el handler consultaba la tabla de bancos directamente en vez de delegar en `banks.simulate`.

#### `get_processes` (`src/handlers/get_processes/`)

- **Trigger**: `httpApi: { method: GET, path: /processes/get-processes }`. Descripción: "Lists the current user's processes, most recent first."
- **Firma**: `handler(event, context)`, decorado `@handle_exceptions` y `@require_auth`.
- **Flujo**: es el handler más simple del servicio y no invoca a ningún otro servicio. Toma `user = event["user"]` (ya inyectado por `require_auth`), llama `Processes.list_by_user(user.id)` -- que internamente hace `select(Processes).where(Processes.user_id == user_id).order_by(Processes.created_at.desc())`, es decir, el orden "más reciente primero" mencionado en la descripción se resuelve en SQL, no en Python. Mapea cada fila a un dict (`id`, `bank_id`, `amount` como `float`, `term`, `rate` como `float`, `stage`, `signature_id`, `created_at`) y responde `generate_response({"processes": [...]}, 200)`.
- **Librerías usadas**: `generate_response`, `handle_exceptions`; `Processes`; `require_auth`.

#### `get_required_files` (`src/handlers/get_required_files/`)

- **Trigger**: `httpApi: { method: GET, path: /processes/get-required-files }`. Descripción: "Returns which file types are still missing for a process, and triggers generate_sign (async) once none are."
- **Firma**: `handler(event, context)`, decorado `@handle_exceptions` y `@require_auth`. Define además una función privada de módulo `_required_file_types(submitted_form: dict) -> set`, que es la única regla de negocio local de este handler: siempre exige `FileType.BANK_CERT`; agrega `FileType.TAX_DECLARATION` si `submitted_form.get("is_tax_declarant")` es verdadero; agrega `FileType.RUT` si `submitted_form.get("is_pep")` es verdadero (PEP = Persona Expuesta Políticamente).
- **Flujo**:
  1. Lee `process_id` de `queryStringParameters`; si no es un UUID válido, `HandledError("invalid process id", 400)`.
  2. Busca el proceso con `Processes.get_by_id(process_id)`; si no existe o `process.user_id != user.id` (chequeo de pertenencia, evita que un usuario consulte archivos de un proceso ajeno), `HandledError("process_not_found", 404)`.
  3. Calcula `required_types` con `_required_file_types(process.submitted_form or {})` (el formulario snapshoteado por `set_process_form`, no el formulario "vivo" del usuario).
  4. Invoca **síncronamente** `files.list_process_files` vía `invoke_sync(function_key="list_process_files", payload={"process_id": str(process_id)}, service="files")`; errores de invocación -> `HandledError("files_lookup_unavailable", 502)`; `statusCode != 200` -> propaga mensaje/código del servicio `files`.
  5. Construye `uploaded_types` a partir de los `file_type` de cada archivo devuelto, y `status = {file_type: file_type in uploaded_types for file_type in required_types}` (un booleano por tipo requerido).
  6. Si **todos** los tipos requeridos están presentes **y** `process.stage == ProcessStage.DOCUMENTS.value`, dispara el worker interno con `invoke_async("generate_sign", {"process_id": str(process_id)})` -- nótese que no pasa `service=`, por lo que `resolve_function_name` usa el `SERVICE` del propio proceso (`processes`), resolviendo a `cdts-{stage}-processes-generate-sign`. Si la *invocación misma* falla (no se observa el resultado del worker, solo la aceptación), `HandledError("generate_sign_unavailable", 502)`.
  7. El guard `process.stage == ProcessStage.DOCUMENTS.value` está comentado explícitamente en el código: evita que un *poll* posterior (proceso ya en `SIGNATURE` o más adelante) vuelva a disparar `generate_sign` y genere una segunda ceremonia de firma para el mismo proceso -- es la salvaguarda de idempotencia del flujo asíncrono.
  8. Responde `generate_response(status, 200)` (el mapa de tipo de archivo -> booleano, nunca el resultado de `generate_sign`, que es fire-and-forget).
- **Librerías usadas**: `HandledError`, `generate_response`, `handle_exceptions`; `FileType` (`libs.orm.files`); `ProcessStage`, `Processes` (`libs.orm.processes`); `require_auth`; `LambdaInvokeError`, `invoke_async`, `invoke_sync` (`libs.utils.lambda_invoke`).

#### `set_process_form` (`src/handlers/set_process_form/`)

- **Trigger**: `httpApi: { method: POST, path: /processes/set-process-form }`. Descripción: "Snapshots the current user's form onto the process and advances its stage to DOCUMENTS."
- **Firma**: `handler(event, context)`, decorado `@handle_exceptions` y `@require_auth`.
- **Flujo**:
  1. Parsea `process_id` del body JSON; UUID inválido -> `HandledError("invalid process id", 400)`.
  2. Busca el proceso y valida pertenencia (`process.user_id != user.id`) igual que `get_required_files`; si falla, `HandledError("process_not_found", 404)`.
  3. Invoca **síncronamente** `forms.get_form` vía `invoke_sync(function_key="get_form", payload={"headers": event.get("headers")}, service="forms")` -- este handler no envía el `user_id` como payload, sino que **reenvía los headers originales de la request** (incluido el `Authorization: Bearer ...`) para que sea `forms.get_form` quien resuelva su propia autenticación y determine de quién es el formulario a devolver. Error de invocación -> `HandledError("form_lookup_unavailable", 502)`; `statusCode != 200` -> propaga mensaje/código de `forms`.
  4. Si la respuesta no trae `form` (clave `"form"` vacía/ausente), `HandledError("form_required", 400)` -- es decir, el usuario debe tener un formulario ya completado en el servicio `forms` antes de poder avanzar el proceso.
  5. Persiste el snapshot con `Processes.set_submitted_form(process_id, form)`, cuyo `UPDATE` hace dos cosas atómicamente: guarda `submitted_form` (columna `JSONB`) y fija `stage = ProcessStage.DOCUMENTS.value` (además de `updated_at = NOW()`) -- de ahí que la "foto" del formulario y el avance de etapa ocurran en la misma operación descrita en la descripción del handler.
  6. Responde `generate_response({id, stage, submitted_form}, 200)`.
- **Librerías usadas**: `HandledError`, `generate_response`, `handle_exceptions`; `Processes`; `require_auth`; `LambdaInvokeError`, `invoke_sync`.

#### Worker `generate_sign` (`src/workers/generate_sign/`)

- **Trigger**: su `function.yml` **no** declara ningún `events` -- solo `memorySize: 1024` y `timeout: 60` (sobreescribiendo los defaults de 512 MB / 15 s del `provider`, necesarios porque este worker descarga un PDF por HTTP, lo procesa con `pypdf`/`reportlab` y encadena dos invocaciones síncronas más a otros servicios). Al no haber `events`, no queda expuesto por `httpApi` ni por ningún otro trigger de AWS: es, tal como dice su propio docstring, "invoke-only, no HTTP" -- solo alcanzable vía `lambda:InvokeFunction`, y el único llamador en todo el backend es `get_required_files` (mismo servicio), que lo invoca de forma asíncrona (`invoke_async`). Pese a no tener evento HTTP, sigue siendo registrado por `build-functions.js` con el nombre convencional `cdts-{stage}-processes-generate-sign`, que es justamente el ARN citado en el bloque IAM.
- **Firma**: `handler(event, context)`. A diferencia de los cuatro handlers HTTP, **no** está decorado con `@handle_exceptions` ni `@require_auth`: no hay sesión de usuario que validar (no hay request HTTP ni header `Authorization`) y el manejo de errores se hace a mano con `try/except` + `db_session.rollback()` manual, devolviendo dicts planos con una clave `"ok"` en vez de los *envelopes* HTTP de `generate_response`.
- **Flujo**:
  1. Toma `process_id = (event or {}).get("process_id")`; si falta, loguea `ERROR` y devuelve `{"ok": False, "error": "missing_process_id"}` sin lanzar excepción.
  2. Busca `Processes.get_by_id(process_id)`; si no existe, loguea `ERROR` y devuelve `{"ok": False, "error": "process_not_found"}`.
  3. **Guard de idempotencia**: si `process.stage != ProcessStage.DOCUMENTS.value`, loguea `WARNING` (ya manejado, o aún no listo) y devuelve `{"ok": False, "skipped": True, "stage": process.stage}` sin tocar nada -- este es el espejo del guard que ya aplica `get_required_files` antes de invocar este worker, y protege contra invocaciones duplicadas o tardías.
  4. Dentro de un `try`:
     - `_fetch_bank(process.bank_id)`: invoca **síncronamente** `banks.get_bank` (`invoke_sync("get_bank", {"queryStringParameters": {"bank_id": str(bank_id)}}, service="banks")`); si la respuesta no es 200, lanza `RuntimeError`.
     - Obtiene `io_url` del banco; si no está configurado, `RuntimeError`.
     - `_fetch_template(io_url)`: descarga la plantilla PDF con `requests.get(io_url, timeout=10)` y `raise_for_status()`.
     - `populate_investment_order(template_pdf, form=process.submitted_form or {}, amount=process.amount, term=process.term, rate=process.rate)` -- función del módulo local `utils/investment_order.py` (ver sección siguiente) que devuelve los bytes del PDF ya poblado.
     - `_signatory_name(process.submitted_form or {})`: concatena `name`, `second_name`, `last_name`, `second_last_name` del formulario (omitiendo los que falten) y usa `"Titular"` como fallback si todos están vacíos.
     - `_create_signature(populated_pdf, signatory)`: construye un evento sintético con forma de API Gateway (`queryStringParameters: {sign_location: json.dumps(SIGNATURE_LOCATION), signatory}`, `body` en base64 del PDF, `isBase64Encoded: True`) y lo pasa a `invoke_sync("create_signature", event, service="signatures")`; si no responde 200, `RuntimeError`; si responde 200, extrae `body["id"]` como `signature_id`.
  5. Si cualquier paso del `try` lanza una excepción, el `except Exception` general la captura, loguea `ERROR` con el detalle, hace `db_session.rollback()` manualmente y devuelve `{"ok": False, "error": "internal_error"}` -- **sin marcar el proceso como fallido**. El docstring del módulo es explícito sobre esta decisión: el proceso queda en `DOCUMENTS`, y como `get_required_files` solo dispara este worker mientras el proceso está en `DOCUMENTS`, el siguiente *poll* del frontend (p. ej. el usuario revisita la página) vuelve a intentarlo -- un reintento incorporado al propio flujo, sin necesidad de un worker separado de timeout/dead-letter.
  6. Si todo tuvo éxito: `Processes.set_signature_id(process_id, signature_id)` -- cuyo `UPDATE` también avanza `stage` a `ProcessStage.SIGNATURE.value` -- seguido de `db_session.commit()` manual, log `INFO`, y retorno `{"ok": True, "process_id": str(process_id), "signature_id": signature_id}`.
- **Librerías de `libs/` usadas**: `db_session` (`libs.core.db`); `Logger` (`libs.core.logger`); `ProcessStage`, `Processes` (`libs.orm.processes`); `invoke_sync` (`libs.utils.lambda_invoke`).
- **Módulo local usado**: `SIGNATURE_LOCATION`, `populate_investment_order` de `services/processes/utils/investment_order.py`.

### Clases y métodos de dominio propios del servicio

El servicio tiene una única carpeta local de utilidades, `services/processes/utils/`, sin un paquete `domain/` separado. Contiene `investment_order.py`, consumido exclusivamente por el worker `generate_sign`.

**Contexto del módulo** (según su propio docstring): la plantilla de orden de inversión de cada banco (`banks.io_key`, un PDF plano por banco bajo `order-forms/<code>.pdf` en el bucket de assets) no tiene campos de formulario (`AcroForm`) rellenables -- esto se confirmó inspeccionando manualmente las 12 plantillas de banco existentes: ninguna trae campos editables y las 12 son idénticas byte a byte en su diagramación (misma grilla de etiquetas/casillas en las mismas coordenadas en cada página; solo cambian el nombre y el logo del banco). Por eso los valores se superponen como texto en coordenadas fijas, medidas una vez sobre la plantilla de Bancolombia y verificadas contra las otras 11.

- **Constantes de módulo**:
  - `_PAGE_W, _PAGE_H = 612.0, 792.0` -- dimensiones de página tamaño Letter en puntos.
  - `_FONT = "Helvetica"`, `_FONT_SIZE = 9` -- tipografía usada para todos los valores superpuestos.
  - `_FIELD_XY`: diccionario que mapea cada uno de 29 nombres de campo (p. ej. `name`, `document_number`, `monthly_income`, `amount`, `term`, `rate`, `opening_date`, `document_number_footer`, etc.) a una tupla `(x, label_bottom_y)` en convención "origen arriba-izquierda" (la `y` crece hacia abajo desde el tope de la página) -- la misma convención que reporta una herramienta de extracción de texto de PDF, de ahí la necesidad de `_to_pdf_y`.
  - `_VALUE_Y_OFFSET = 14.0` -- desplazamiento vertical (en puntos) entre el borde inferior de la etiqueta impresa y donde se dibuja el valor, de modo que quede dentro de la misma caja bordeada.
  - `_TAX_DECLARANT_YES/_NO`, `_PEP_YES/_NO`: coordenadas (en la misma convención top-origin) de los centros de las casillas de las dos preguntas Sí/No de la plantilla (declarante de renta, PEP).
  - `SIGNATURE_LOCATION` (único símbolo exportado además de la función principal): lista con un dict `{page: 1, x_pct, y_pct, width_pct, height_pct}` describiendo la caja "Firma del titular" de la plantilla, ya en el formato que esperan `signatures.create_signature` / `stamp_drawing_on_pdf` (página 1-indexada, porcentajes `x_pct`/`y_pct` desde la esquina superior izquierda). Es compartida por los 12 bancos porque la caja de firma está en el mismo lugar en todas las plantillas; la usa el worker `generate_sign` al construir el payload de `create_signature`.

- **`_to_pdf_y(y_top_origin: float) -> float`**: convierte una coordenada medida en la convención "origen arriba" a la convención nativa de `reportlab`/PDF ("origen abajo-izquierda"), simplemente `_PAGE_H - y_top_origin`.

- **`_text(value) -> str`**: normaliza un valor de formulario para dibujarlo: devuelve `"-"` si `value` es `None` o cadena vacía; en cualquier otro caso devuelve `str(value)`.

- **`_money(value) -> str`**: formatea un valor monetario como `"$ N.NNN"` (separador de miles, cero decimales) construyendo un `Decimal(str(value))`; devuelve `"-"` si `value` es `None` o si la conversión a `Decimal` lanza `InvalidOperation` (valor no numérico).

- **`populate_investment_order(template_pdf: bytes, *, form: dict, amount, term: int, rate) -> bytes`**: función principal y única "regla de negocio" exportada del módulo.
  - Recibe los bytes del PDF plantilla del banco (`template_pdf`), el snapshot de formulario del proceso (`form` -- exactamente la forma que devuelve `forms.get_form`, según aclara el docstring de la función) y los términos comerciales del proceso (`amount`, `term`, `rate`).
  - Construye un diccionario `values` con los 29 campos de `_FIELD_XY`: los datos personales se formatean con `_text` (nombre, documento, nacionalidad, fechas, etc.); los montos (`monthly_income`, `monthly_expenses`, `total_assets`, `total_liabilities`, `amount`) con `_money`; `term` se formatea como `"{term} dias"`; `rate` como `"{rate:.2f}% E.A."`; `opening_date` es la fecha de hoy (`datetime.now()`) formateada `dd/mm/YYYY` (es decir, no la fecha de creación del proceso, sino la fecha en que corre el worker); y `document_number_footer` repite el número de documento (aparece también al pie de la plantilla).
  - Dibuja cada valor con `reportlab.pdfgen.canvas.Canvas` sobre un buffer en memoria del tamaño de la página, usando `drawString` en la posición `(x, _to_pdf_y(label_bottom + _VALUE_Y_OFFSET))` para cada campo.
  - Marca con una `"X"` en negrita (función interna `_mark_checkbox`, que cambia temporalmente a `Helvetica-Bold` tamaño 10 y centra el trazo con `drawCentredString`) la casilla "Sí" o "No" correspondiente, según `form.get("is_tax_declarant")` y `form.get("is_pep")` sean verdaderos o falsos.
  - Fusiona esa única página de overlay sobre la página 0 de la plantilla con `pypdf`: lee ambos PDFs (overlay y plantilla) con `PdfReader`, hace `template_reader.pages[0].merge_page(overlay_reader.pages[0])`, y escribe el resultado con `PdfWriter().append(template_reader)` a un buffer de salida.
  - Devuelve los bytes del PDF resultante. El propio docstring aclara el límite de responsabilidad de esta función: no estampa, no firma ni agrega una página de evidencia -- eso ocurre después, en la ceremonia de `signatures` a la que el worker `generate_sign` entrega este documento.

---

## 6. Servicio `signatures`

> Nota de alcance: `services/signatures/_legacy/` contiene una implementación previa completa (handlers `create`, `get`, `consent`, `request_otp`, `verify_otp`, `sign`, `verify`, `validate_id_front/back`, `validate_face`, `register_signature`, `upload_url` y su propia carpeta `utils/` con `evidence.py`, `mock_ca.py`, `evidence_package.py`) que `functions.js` **no** auto-registra porque solo escanea `src/handlers` y `src/workers` — es código legado conservado como referencia, no desplegado, y no se documenta en detalle aquí.

### Propósito

`signatures` es el microservicio de firma digital de documentos con evidencia del backend. Expone una ceremonia de firma por HTTP (pensada para ser consumida por un microfrontend público) en la que un firmante: sube un documento PDF y declara dónde debe firmarse, completa un formulario con su email, sube tres evidencias biométricas (foto del documento de identidad por ambos lados y una selfie) que se validan automáticamente contra Amazon Rekognition, dibuja/sube su firma manuscrita, recibe y verifica un código OTP de un solo uso por correo, y finalmente dispara de forma asíncrona el proceso criptográfico de firma: estampado del garabato sobre el PDF, emisión de un certificado de transacción efímero por una Entidad Certificadora (CA) mock interna, firma del documento en formato **PAdES-B baseline**, y generación de una página de evidencia/auditoría que se anexa al PDF antes de firmarlo. El resultado (`signed.pdf`) y los artefactos intermedios quedan en un bucket S3 propio del servicio.

A diferencia de lo que describe `docs/signatures-v2.md` (que documenta una iteración anterior/paralela del servicio, con conceptos como `sign_id`, `X-Service-Key`, un endpoint `consent` explícito y un endpoint público `/verify`), el código efectivamente activo bajo `src/handlers/` y `src/workers/` implementa una máquina de estados más simple y con nombres distintos: la tabla `Signatures` (en `libs/orm/signatures.py`, compartida por todo el servicio) usa una clave primaria `id` (UUID), y el campo `stage` transita por `FORM → BIOMETRICS → SIGNATURE → OTP → SIGNING → SIGNED` (o `FAILED` en cualquier punto). No hay un paso de "consentimiento" separado ni un endpoint `/verify` activos en este código; esa lógica, si existió, quedó en `_legacy/`. Esta sección documenta exclusivamente lo que el runtime despliega hoy.

El servicio es deliberadamente agnóstico del dominio que lo consume: no sabe qué es un "proceso" ni un "CDT"; solo recibe bytes de un PDF, coordenadas de firma y datos del firmante, y devuelve un documento firmado con su evidencia. La integración saliente real que el código expone hacia otros servicios es, por ahora, un webhook único y preconfigurado (`sign_trigger`, vía SSM `SSM_SIGN_TRIGGER_PATH`) que notifica `{signature_id, stage}` cuando una firma llega a un estado terminal — no hay todavía un consumidor provisto para ese parámetro SSM, así que la función está presente en el código pero "apagada por ausencia" en cualquier stage donde no se haya configurado.

### Arquitectura de despliegue

**`serverless.yml`**

- `provider`: runtime `python3.12`, región `us-east-1` (override por `--region`), `stage` por defecto `dev`, `stackName: cdts-${sls:stage}-signatures`, `memorySize: 1024` (override por función, ver `sign_doc`), `timeout: 15` segundos (también overrideable por función), `logRetentionInDays: 14`.
- `httpApi.cors.allowedHeaders`: lista estándar de CORS para API Gateway HTTP API (`Content-Type`, `X-Amz-Date`, `Authorization`, `X-Api-Key`, `X-Amz-Security-Token`, `X-Amz-User-Agent`) más **`X-Debug-OTP-Signature`**. Este último header está habilitado en CORS y hay un parámetro SSM reservado para él (`SSM_DEBUG_OTP_KEY_PATH`, ver abajo), pero **el handler `set_otp` leído en este repositorio no implementa ninguna lógica de HMAC ni de disclosure de OTP en claro** — es infraestructura dejada lista (header permitido, variable de entorno, permiso IAM sobre el parámetro SSM) para una función que, a la fecha de esta lectura del código, no está cableada en el handler activo. Un comentario en `src/workers/sign_trigger/handler.py` (línea 12) incluso da por sentado que "ya se usa en `set_otp`", lo cual no se corresponde con el código de `set_otp/handler.py` tal como está — es una inconsistencia entre comentario y código que vale la pena señalar en una auditoría.
- `environment` (variables, en el orden del archivo, con el propósito citado de sus propios comentarios):
  - `STAGE`: el stage actual (`${sls:stage}`).
  - `SERVICE: signatures` — comentario del yml: *"Lets verify_otp invoke its sibling `sign` Lambda via libs.utils.lambda_invoke without naming 'signatures' again at the call site."* (el nombre real del handler que invoca a su hermano es hoy `resolve_otp`, que invoca a `sign_doc`; el comentario quedó con la nomenclatura anterior).
  - `SSM_DB_PATH: /cdts/${sls:stage}/db` — credenciales Postgres compartidas (leídas por `libs/core/db.py`).
  - `SSM_SMTP_PATH: /cdts/${sls:stage}/smtp` — credenciales SMTP compartidas (leídas por `libs/core/mailer.py`).
  - `SSM_FRONTEND_PATH: /cdts/${sls:stage}/frontend` — comentario: *"`create` handler builds sign_url ... using this path"*; en el código activo ningún handler leído construye realmente un `sign_url` a partir de esta variable (no aparece referenciada en `create_signature/handler.py` ni en ningún otro handler activo) — otro resto de un diseño anterior.
  - `SSM_SIGNATURES_SERVICE_KEY: /cdts/${sls:stage}/signatures/service-key` — comentario: M2M shared secret para `POST /signatures` vía header `X-Service-Key`. Al igual que el punto anterior, ningún handler activo lee esta variable ni valida ese header; `create_signature` no tiene ninguna verificación de autenticación M2M.
  - `SSM_DEBUG_OTP_KEY_PATH: /cdts/${sls:stage}/signatures/debug-otp-key` — feature opcional, dev-only, de disclosure de OTP en claro para tests de integración automatizados; "desactivada por ausencia" del parámetro SSM. No implementada en el handler activo `set_otp` (ver arriba).
  - `SSM_SIGN_TRIGGER_PATH: /cdts/${sls:stage}/signatures/sign-trigger-webhook` — URL de un webhook fijo (no por-firma) al que `sign_trigger` hace POST `{signature_id, stage}` cuando una firma llega a `SIGNED` o `FAILED`. Sin consumidor provisto todavía; "desactivada por ausencia" del parámetro.
  - `SIGNATURES_BUCKET: cdts-${sls:stage}-signatures` — bucket propio del servicio, desacoplado de `files`; todos los PDFs, biometrías, firma dibujada y PDFs firmados viven bajo `signatures/{signature_id}/...`.
  - `SIGNATURE_TIMEOUT_QUEUE_URL: !Ref SignatureTimeoutQueue` — comentario: `create_signature` encola un mensaje retrasado por firma aquí (`DelaySeconds = SIGNING_WINDOW`); `check_signature_timeout` lo consume y marca la fila `FAILED` si nunca llegó a `SIGNED`.
  - `SIGNING_TIMEOUT_QUEUE_URL: !Ref SigningTimeoutQueue` — comentario: `resolve_otp` encola aquí (`DelaySeconds = SIGNING_TIMEOUT`) justo cuando entrega la firma a `sign_doc`; `check_signing_timeout` lo consume y marca `FAILED` si `sign_doc` nunca la llevó a `SIGNED`.
  - `SIGN_LAMBDA_READY: "true"` — comentario: gate para que `verify_otp` (hoy `resolve_otp`) invoque de forma asíncrona la Lambda interna `sign` (hoy `sign_doc`). El código de `resolve_otp/handler.py` leído **no** condiciona la llamada a `invoke_async("sign_doc", ...)` con esta variable de entorno — la invoca siempre, sin leer `SIGN_LAMBDA_READY`; el env var queda declarado pero sin lectura activa en el handler actual.

  (Las tres observaciones anteriores — `SSM_FRONTEND_PATH`, `SSM_SIGNATURES_SERVICE_KEY` y `SIGN_LAMBDA_READY` sin lectura real, y `X-Debug-OTP-Signature`/`SSM_DEBUG_OTP_KEY_PATH` sin implementación — son consistentes entre sí: documentan la transición de una versión previa del servicio, descrita en `docs/signatures-v2.md`, hacia el diseño más simple que hoy vive en `src/handlers` y `src/workers`. El `serverless.yml` no fue depurado por completo tras ese cambio.)

- `iam.role` (`name: cdts-${sls:stage}-signatures-lambda`), statements, en orden:
  1. `ssm:GetParametersByPath` + `ssm:GetParameter` sobre los paths de DB, SMTP, frontend, `signatures/service-key`, `signatures/debug-otp-key`, `signatures/sign-trigger-webhook` y los dos parámetros de la CA mock (`mock-ca/root/cert-pem`, `mock-ca/root/private-key-pem`). Comentario: `mock_ca._load_root_ca()` (hoy `libs/utils/signature_ca.py::_load_root_ca`) lee los dos últimos.
  2. `kms:Decrypt` sobre `Resource: '*'`. Comentario: los `SecureString` de SSM están cifrados con la CMK administrada `alias/aws/ssm`, que rota y no se puede referenciar por ARN fijo; el acotamiento real de qué se puede leer lo da el statement de `ssm:GetParameter` anterior, no este.
  3. `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` sobre `arn:aws:s3:::cdts-${sls:stage}-signatures/*` — lectura del PDF original, evidencias y firma dibujada; escritura del PDF firmado y los artefactos generados.
  4. `s3:ListBucket` sobre el bucket (sin `/*`) — comentario: necesario para que un `HeadObject`/probe de extensión devuelva 404 real en vez de 403 cuando falta un objeto (patrón heredado de la lógica de "probar `.jpg` antes de `.png`" de `_legacy/utils/evidence.py`; en el código activo, `upload_biometrics` decide la extensión al momento de generar la URL presignada, así que el probing explícito ya no es necesario, pero el permiso quedó).
  5. `rekognition:DetectText`, `rekognition:DetectFaces` sobre `Resource: '*'` — usadas por `libs/utils/biometrics.py` para validar ID front/back (DetectText) y selfie (DetectFaces) directamente contra el objeto S3 (variante `S3Object`, sin mover bytes).
  6. `lambda:InvokeFunction` sobre `arn:aws:lambda:...:function:cdts-${sls:stage}-signatures-*` — acotado a las propias Lambdas del servicio; usado por `resolve_otp` (invoca `sign_doc`) y por `libs/utils/signature_notifications.py` (invoca `sign_trigger` y `notify_signed`).
  7. `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` sobre las dos colas de timeout. Comentario: Serverless también agrega automáticamente los permisos de consumidor para el trigger `sqs:`, pero se listan explícitamente "para que el rol sea auto-documentado".
- `plugins`: `serverless-python-requirements` (empaqueta las dependencias Python del `requirements.txt`).
- `custom.pythonRequirements`: `dockerizePip: false`, `slim: false`, `fileName: requirements.txt` — instala las dependencias con el Python local (sin Docker) y no aplica "slimming" (no quita símbolos de debug/tests de las wheels), probablemente porque algunas de las librerías de PDF/criptografía no toleran bien el slimming.
- `package.patterns`: excluye todo por defecto (`'!**'`) y vuelve a incluir `src/**`, `libs/**` (la copia local generada por `functions.js`) y `utils/**` (vacío hoy, ver sección de clases de dominio); excluye `__pycache__`, `.pyc`, y los archivos de test colocalizados (`test.py`, `integration.py`, `conftest.py`) para que no viajen en el paquete de despliegue.
- `functions: ${file(./functions.js):build}` — delega la construcción del mapa de funciones a `functions.js` (ver más abajo).
- `resources.Resources`:
  - `SignaturesBucket` (`AWS::S3::Bucket`, nombre `cdts-${sls:stage}-signatures`): `PublicAccessBlockConfiguration` completo (todo en `true`), `OwnershipControls: BucketOwnerEnforced`, cifrado `SSE-AES256` por defecto, `CorsConfiguration` permitiendo `PUT/GET/HEAD` desde cualquier origen (comentario: necesario porque `upload_biometrics` devuelve URLs presignadas que el navegador del firmante usa para `PUT` directo, y `get_signature` expone URLs presignadas `GET` que el microfrontend usa para renderizar el PDF), y `LifecycleConfiguration` que expira **todo** lo que esté bajo el prefijo `transactions/` a los 30 días (comentario: proyecto académico, sin necesidad de retención larga — nota: este prefijo del lifecycle (`transactions/`) no coincide con el prefijo real que usan los handlers activos, que escriben bajo `signatures/{signature_id}/...`, no `transactions/{signature_id}/...`; es otro remanente del diseño descrito en `docs/signatures-v2.md`, por lo que **la regla de expiración de 30 días, tal como está escrita hoy, no aplica a los objetos que el código activo efectivamente sube**).
  - `SignatureTimeoutQueue` (`AWS::SQS::Queue`, `cdts-${sls:stage}-signatures-timeout`): `VisibilityTimeout: 60`, `MessageRetentionPeriod: 345600` (4 días, default de SQS). El comentario del yml aclara que el `DelaySeconds` real (900s = `SIGNING_WINDOW`) se setea en el `send_message` de `create_signature`, no en la cola — SQS permite hasta 900s de `DelaySeconds` por mensaje, que es exactamente el máximo que usa este mecanismo de timeout.
  - `SigningTimeoutQueue` (`AWS::SQS::Queue`, `cdts-${sls:stage}-signatures-signing-timeout`): `VisibilityTimeout: 30`, misma retención. `DelaySeconds` real = 60s (`SIGNING_TIMEOUT`), seteado por `resolve_otp`.
  - Mecanismo de timeout por delay queues: en vez de un scheduler externo, el propio productor (`create_signature` o `resolve_otp`) encola un mensaje con `DelaySeconds` igual a la ventana que quiere vigilar; SQS no entrega ese mensaje hasta que pasa el delay. El worker consumidor (`check_signature_timeout` / `check_signing_timeout`) solo se ejecuta cuando el mensaje efectivamente se vuelve visible, relee la fila por `signature_id`, y si todavía no llegó al estado esperado la marca `FAILED`. Es un patrón de "sí o sí vamos a revisar esto en N segundos" sin necesidad de un cron ni de un step function.
  - `Outputs.SignaturesBucketName`: expone el nombre del bucket como output de CloudFormation.

**`requirements.txt`** (cada línea, con su uso inferido del código):
- `sqlalchemy==2.0.34` — ORM; `libs/orm/signatures.py` define `Signatures` como `Base` declarativa de SQLAlchemy 2.x (`Mapped[...]`, `mapped_column`).
- `pg8000==1.31.2` — driver Postgres puro-Python usado por el engine (`postgresql+pg8000://...` en `libs/core/db.py`).
- `scramp==1.4.17` — implementación de SCRAM-SHA-256, dependencia de autenticación de `pg8000` contra Postgres.
- `reportlab==4.2.5` — generación de PDF desde cero; usada por `libs/utils/signature_stamp.py` (dibuja el garabato sobre un canvas y lo mergea en la página) y por `libs/utils/signature_audit_page.py` (construye la página de evidencia completa con texto, grilla de imágenes y fuentes embebidas).
- `pypdf==5.1.0` — lectura/escritura/merge de PDFs existentes; usada en `signature_stamp.py` (`PdfReader`/`PdfWriter`/`merge_page`) y en `sign_doc/handler.py` (`_append_page`, para anexar la página de auditoría al PDF estampado antes de firmarlo).
- `cryptography==43.0.3` — primitivas X.509/RSA; usada en `libs/utils/signature_ca.py` para generar el par de llaves RSA-2048 del certificado efímero, construir el certificado leaf (`x509.CertificateBuilder`) y cargar el certificado/llave de la CA raíz desde PEM.
- `asn1crypto==1.5.1` — comentario propio del archivo: *"pulled in transitively but pinned here for reproducibility"*; usada directamente en `signature_ca.py` para convertir PEM/DER a las estructuras `asn1crypto.x509.Certificate` / `asn1crypto.keys.PrivateKeyInfo` que `pyhanko` necesita internamente para firmar.
- `pyhanko==0.34.1` — motor de firma PAdES: `IncrementalPdfFileWriter`, `PdfSigner`, `SimpleSigner`, `SigFieldSpec`/`append_signature_field`, usados en `signature_ca.py::sign_pdf_pades_b` para producir la firma PAdES-B baseline embebida.
- `pyhanko-certvalidator==0.30.2` — provee `SimpleCertificateStore`, usado por `signature_ca.py::_build_signer` para registrar la CA raíz como emisora de confianza del `SimpleSigner` (no hay código activo de *validación* de cadena — eso vivía en el endpoint `/verify` legado — solo se usa el registro de certificados al momento de firmar).
- `requests==2.32.3` — comentario propio: *"sign_trigger POSTs to the preconfigured webhook with this"*; es, en efecto, la única dependencia HTTP saliente usada por `src/workers/sign_trigger/handler.py`.

**Auto-registro de handlers.** `services/signatures/functions.js` hace dos cosas antes de delegar: (1) resincroniza `backend/libs/` dentro de `services/signatures/libs/` (borra y copia con `fs.cpSync`, recursivo) — esta carpeta `libs/` local está en `.gitignore` y existe solo para que `serverless-python-requirements`/el empaquetado incluya el código compartido junto al código del servicio, ya que Lambda no puede resolver un import fuera del paquete desplegado; y (2) exporta `module.exports.build = require('../../utils/build-functions')(__dirname)`, que es lo que `serverless.yml` invoca como `functions: ${file(./functions.js):build}`.

`backend/utils/build-functions.js` es el motor genérico de autodescubrimiento, reutilizado por todos los servicios del backend (no es específico de `signatures`). Exporta una función `(serviceDir) => async ({options, resolveConfigurationProperty}) => {...}` — la firma async que Serverless Framework v3 espera para una propiedad de configuración resuelta dinámicamente. Al ejecutarse: lee `service` de la config de Serverless y `stage` de las opciones de CLI (`--stage`, default `dev`); recorre, en este orden, las carpetas `src/handlers`, `src/scheduled` y `src/workers` dentro del servicio (para `signatures` solo existen `handlers` y `workers`); dentro de cada tipo, itera las subcarpetas en orden alfabético (`fs.readdirSync(...).sort()`), valida con `assertSnakeCase` que el nombre de carpeta sea `snake_case` (porque Python no puede importar carpetas con guiones) y lanza error de build si no lo es; exige que exista un `function.yml` en cada carpeta (si falta, lanza error de build); carga ese `function.yml` con `js-yaml` como el "custom" de esa función; y construye la entrada final como `{ name: "cdts-{stage}-{service}-{folder-con-guiones}", handler: "src/{tipo}/{folder}/handler.handler", ...custom }` — es decir, el `function.yml` puede sobre-escribir `name` o `handler` como escape hatch, pero el resto de sus claves (p. ej. `events`, `memorySize`, `timeout`) se mezclan tal cual en la función de Serverless. Así, por ejemplo, la carpeta `src/workers/sign_doc` se convierte en la función `cdts-dev-signatures-sign-doc`, con handler `src/workers/sign_doc/handler.handler`, y los `memorySize: 2048`/`timeout: 300` de su `function.yml` pasan intactos a CloudFormation.

### Handlers y workers

Todos los handlers HTTP comparten el mismo patrón de validación manual (no hay un decorador de autenticación: la "autenticación" de la ceremonia es, en la práctica, el conocimiento del UUID `signature_id`, que cada handler recibe como parámetro y resuelve con `Signatures.get_by_id`) y el mismo decorador `@handle_exceptions` (definido en `libs/core/responses.py`), que: ejecuta el handler, hace `db_session.commit()` si no hubo excepción; si se lanzó un `HandledError`, hace `rollback`, loguea `WARNING` y devuelve `generate_response({"error": e.message}, e.status_code)`; cualquier otra excepción hace `rollback`, loguea `ERROR` con traceback y devuelve 500 genérico; y en un `finally` cierra la sesión (`db_session.close()`) para que un contenedor Lambda "caliente" no retenga una transacción abierta entre invocaciones. Los **workers** (invocados por SQS o por invocación Lambda directa, nunca por HTTP) no usan `@handle_exceptions`: manejan sus propios `try/except` y hacen `commit`/`rollback`/`close` explícitos sobre `db_session`.

#### `src/handlers/create_signature`

- **Trigger** (`function.yml`): `POST /signatures/create-signature`.
- **Firma**: `handler(event, context)`, decorado con `@handle_exceptions`.
- **Flujo**: lee `sign_location` (JSON, debe parsear a una lista no vacía) y `signatory` de los query params; lee el cuerpo crudo de la petición como los bytes del PDF (decodifica base64 si `event["isBase64Encoded"]`); genera una key `f"{_uuid7()}.pdf"`, donde `_uuid7()` es una implementación local de UUIDv7 (RFC 9562: 48 bits de timestamp en ms + bits de versión/variante + aleatoriedad) usada — a diferencia del `id` de la fila, que sigue siendo `uuid4` — porque una key de S3 ordenada por tiempo es más amigable para listar/depurar; sube el PDF a `SIGNATURES_BUCKET` vía `upload_from_bytes`; crea la fila con `Signatures.create(doc_s3_key, sign_location, signatory)` (arranca en `stage=FORM`); encola un mensaje de timeout en `SIGNATURE_TIMEOUT_QUEUE_URL` con `delay_seconds=SIGNING_WINDOW` (900s) conteniendo `{"signature_id": ...}`; responde 200 con `id, stage, doc_s3_key, signatory, sign_location`.
- **Errores manejados**: 400 si falta `sign_location`, si no es JSON válido, si no es lista no vacía, si falta `signatory`, o si el cuerpo está vacío.
- **Clases/métodos usados**: `Signatures.create` (ORM); `upload_from_bytes` y `send_message` (`libs/core/s3.py`, `libs/core/sqs.py`); `HandledError`/`generate_response`/`handle_exceptions` (`libs/core/responses.py`); `SIGNING_WINDOW` (`libs/orm/signatures.py`).
- No hay autenticación M2M (ningún `X-Service-Key` ni similar en el código activo, pese a lo declarado en `environment`).

#### `src/handlers/get_required_biometrics`

- **Trigger**: `GET /signatures/get-required-biometrics`.
- **Firma**: `handler(event, context)`, `@handle_exceptions`.
- **Flujo**: lee `signature_id` de query params y lo parsea como UUID; busca la fila; 410 si pasó `created_at + SIGNING_WINDOW`; calcula `status = {biometric_type: bool(valor de la columna correspondiente)}` para los tres tipos definidos en `BIOMETRIC_COLUMNS` (`ID_FRONT`, `ID_BACK`, `FACE`); si la fila está en `stage=BIOMETRICS` y las tres ya están presentes, llama `Signatures.advance_to_signature_stage(signature_id)` (efecto lateral de avance de stage dentro de un GET); responde 200 con el diccionario `status`.
- **Clases/métodos usados**: `Signatures.get_by_id`, `Signatures.advance_to_signature_stage`, `BIOMETRIC_COLUMNS`, `SIGNING_WINDOW`, `SignatureStage` (todos de `libs/orm/signatures.py`).

#### `src/handlers/get_signature`

- **Trigger**: `GET /signatures/get-signature`. El `description` del `function.yml` dice "20-minute signing window", pero la constante real que todos los handlers usan (`SIGNING_WINDOW` en `libs/orm/signatures.py`) es de **15 minutos** (900s) — inconsistencia entre el comentario de `function.yml` y el código.
- **Firma**: `handler(event, context)`, `@handle_exceptions`.
- **Flujo**: endpoint público de solo lectura para que el microfrontend reconstruya su estado en cualquier momento. Lee y valida `signature_id`; busca la fila (404 si no existe); calcula `expires_at = created_at + SIGNING_WINDOW` y devuelve 410 si ya expiró, **excepto** si el `stage` está en `_NO_EXPIRY_STAGES = (SIGNING, SIGNED, FAILED)` — el comentario explica por qué: `SIGNING` se excluye deliberadamente porque siempre se resuelve dentro de `SIGNING_TIMEOUT`, y un 410 justo en el borde de la ventana cortaría el polling del front un instante antes de que la fila llegue a `SIGNED`; genera URLs de descarga presignadas (`presign_download`) para el documento original y, si existen, para `raw_signed_s3_key` y `signed_s3_key`; responde con `id, stage, sign_location, doc_url, expires_at, raw_signed_url, signed_url, doc_hash, signed_hash, signed_at` — deliberadamente sin datos biométricos ni OTP.
- **Clases/métodos usados**: `Signatures.get_by_id`, `SIGNING_WINDOW`, `SignatureStage`; `presign_download` (`libs/core/s3.py`).

#### `src/handlers/resolve_otp`

- **Trigger**: `POST /signatures/resolve-otp`.
- **Firma**: `handler(event, context)`, `@handle_exceptions`.
- **Flujo**: valida `signature_id` y `code` (regex `^\d{6}$`); busca la fila; 410 si expiró la ventana de firma; 409 si no está en `stage=OTP`; 409 si no hay `otp_hash`/`otp_at` (OTP nunca solicitado); 401 si `otp_at + OTP_TTL` (2 min) ya pasó; compara `sha256(code)` contra `row.otp_hash` — si **no coincide**: incrementa el contador con `Signatures.register_failed_otp_attempt`; si con ese incremento llega a `MAX_OTP_TRIES` (3), marca la fila `FAILED` (`Signatures.mark_failed`), dispara `notify_terminal_state(signature_id, "FAILED")` y responde 429 `otp_max_attempts`; si no, responde 401 `otp_invalid` con `attempts_left`. Si **coincide**: construye `signing_data` con `_capture_telemetry(event)` (IP de `requestContext.http.sourceIp`, `User-Agent`, `Accept-Language` y timestamp de resolución — el comentario explica que esta es la única oportunidad de capturar esos datos de la request HTTP, porque `sign_doc` corre después, de forma asíncrona y desacoplado del request original); llama `Signatures.start_signing(signature_id, signing_data)` (pasa a `stage=SIGNING`, limpia `otp_hash`); encola un mensaje en `SIGNING_TIMEOUT_QUEUE_URL` con `delay_seconds=SIGNING_TIMEOUT` (60s); invoca **asíncronamente** `sign_doc` vía `invoke_async("sign_doc", {"signature_id": ...})` — si la invocación falla al nivel de submission, lanza `HandledError("sign_doc_unavailable", 502)`; responde 200 con `id, stage`.
- **Quién dispara a quién**: `resolve_otp` → (SQS, delay 60s) `SigningTimeoutQueue` → `check_signing_timeout`; `resolve_otp` → (invoke Lambda async, `InvocationType=Event`) → `sign_doc`.
- **Clases/métodos usados**: `Signatures.get_by_id/register_failed_otp_attempt/mark_failed/start_signing`; `MAX_OTP_TRIES`, `OTP_TTL`, `SIGNING_TIMEOUT`, `SIGNING_WINDOW`, `SignatureStage`; `send_message`; `invoke_async`/`LambdaInvokeError` (`libs/utils/lambda_invoke.py`); `notify_terminal_state` (`libs/utils/signature_notifications.py`).

#### `src/handlers/set_biometrics`

- **Trigger**: `POST /signatures/set-biometrics`.
- **Firma**: `handler(event, context)`, `@handle_exceptions`.
- **Flujo**: lee del body JSON `signature_id`, `biometric_type` (debe ser `ID_FRONT`/`ID_BACK`/`FACE`) y `s3_key`; valida que `s3_key` empiece con `f"signatures/{signature_id}/"` (400 si no, para que un cliente no pueda apuntar a objetos de otra firma); busca la fila (404); 410 si expiró; 409 si no está en `stage=BIOMETRICS`; 409 `biometric_already_set` si esa columna ya tiene valor (no se puede re-validar una evidencia ya aceptada); llama al analizador correspondiente de `libs/utils/biometrics.py` (`analyze_id_front`/`analyze_id_back`/`analyze_face`) pasándole bucket+key; si `is_valid`, persiste con `Signatures.set_biometric_key`; responde siempre 200 con `{"is_valid": ..., "reason": ...}` (nunca error HTTP por una foto rechazada — es un resultado de negocio, no un fallo de servidor).
- **Clases/métodos usados**: `Signatures.get_by_id/set_biometric_key`, `BIOMETRIC_COLUMNS`, `SIGNING_WINDOW`, `SignatureStage`; `analyze_face/analyze_id_back/analyze_id_front` (`libs/utils/biometrics.py`).

#### `src/handlers/set_otp`

- **Trigger**: `POST /signatures/set-otp`.
- **Firma**: `handler(event, context)`, `@handle_exceptions`.
- **Flujo**: valida `signature_id`; busca fila; 410 si expiró; 409 si no está en `stage=OTP`; genera un código de 6 dígitos con `secrets.randbelow(1_000_000)` (criptográficamente seguro, no `random`); persiste `Signatures.set_otp(signature_id, sha256(otp))` (resetea `otp_tries=0` y `otp_at=NOW()` — este mismo endpoint sirve tanto para la primera emisión como para un reenvío, de forma idempotente respecto al contador de intentos); renderiza el email con `render_otp_email` (`libs/utils/otp_email.py`) y lo envía con `send_email`; si el mailer rechaza el envío, solo loguea `ERROR` (no lanza excepción — el estado de la fila ya cambió y no se revierte por un fallo de correo); responde con `id, stage, email_sent, expires_at`.
- Nótese: **el código de este handler no implementa** la disclosure de OTP en claro bajo HMAC (`X-Debug-OTP-Signature`) que sugieren el `environment.SSM_DEBUG_OTP_KEY_PATH` del `serverless.yml` y el comentario de `sign_trigger`; el OTP solo sale por correo.
- **Clases/métodos usados**: `Signatures.get_by_id/set_otp`, `OTP_TTL`, `SIGNING_WINDOW`, `SignatureStage`; `render_otp_email` (`libs/utils/otp_email.py`); `send_email` (`libs/core/mailer.py`); `Logger` (`libs/core/logger.py`).

#### `src/handlers/set_signature_draw`

- **Trigger**: `POST /signatures/set-signature-draw`.
- **Firma**: `handler(event, context)`, `@handle_exceptions`.
- **Flujo**: valida `signature_id`; lee el cuerpo crudo como bytes de la imagen (decodifica base64 si aplica); rechaza con 422 si pesa menos de 100 bytes (`draw_invalid_empty`) o con 413 si pesa más de 2 MiB (`draw_invalid_too_large`) — el comentario aclara que el formato (PNG vs SVG) todavía no está decidido, por eso el chequeo es solo de tamaño, no de contenido; busca fila (404); 410 si expiró; 409 si no está en `stage=SIGNATURE`; sube el archivo a `f"signatures/{signature_id}/draw.bin"` con `upload_from_bytes` (content type genérico `application/octet-stream`, consistente con que el formato es agnóstico); persiste con `Signatures.set_draw_key` (avanza a `stage=OTP`); responde con `id, stage, draw_s3_key`.
- **Clases/métodos usados**: `Signatures.get_by_id/set_draw_key`, `SIGNING_WINDOW`, `SignatureStage`; `upload_from_bytes`.

#### `src/handlers/set_signature_form`

- **Trigger**: `POST /signatures/set-signature-form`.
- **Firma**: `handler(event, context)`, `@handle_exceptions`.
- **Flujo**: valida `signature_id`; valida `email` con `valid_email` (`libs/utils/validators.py`, regex simple + longitud ≤320); busca fila (404); 410 si expiró; 409 si no está en `stage=FORM`; persiste `Signatures.set_email` (setea `email` y avanza a `stage=BIOMETRICS`); responde con `id, stage, email`.
- Es, en la práctica, el paso que cierra el "FORM" inicial de la ceremonia (completa el dato de contacto del firmante) y determina a qué email llegará después el OTP y el correo de "documento firmado".
- **Clases/métodos usados**: `Signatures.get_by_id/set_email`, `SIGNING_WINDOW`, `SignatureStage`; `valid_email`.

#### `src/handlers/upload_biometrics`

- **Trigger**: `POST /signatures/upload-biometrics`.
- **Firma**: `handler(event, context)`, `@handle_exceptions`.
- **Flujo**: valida `signature_id`, `biometric_type` (uno de `ID_FRONT`/`ID_BACK`/`FACE`) y `content_type` (`image/jpeg` o `image/png`, default `image/jpeg`); busca fila (404); 410 si expiró; 409 si no está en `stage=BIOMETRICS`; calcula la extensión según el content type y construye la key determinística `f"signatures/{signature_id}/{prefijo}.{ext}"` (prefijos `id_front`/`id_back`/`face`); genera la URL presignada de `PUT` con `presign_upload` (TTL fijo de 900s, reportado también en la respuesta como `expires_in`); responde con `upload_url, key, content_type, expires_in`.
- Es el paso previo obligatorio a `set_biometrics`: el front sube el binario directo a S3 con esta URL, y luego llama a `set_biometrics` pasando la misma `key` para que Rekognition la analice.
- **Clases/métodos usados**: `Signatures.get_by_id`, `BiometricType`, `SIGNING_WINDOW`, `SignatureStage`; `presign_upload` (`libs/core/s3.py`).

#### `src/workers/check_signature_timeout`

- **Trigger** (`function.yml`): evento SQS sobre `Fn::GetAtt: [SignatureTimeoutQueue, Arn]`, `batchSize: 5`, `timeout: 30`. El comentario del propio `function.yml` explica por qué usa la forma larga `Fn::GetAtt` en vez del tag corto `!GetAtt`: `js-yaml` (usado por `build-functions.js` para parsear `function.yml`) no entiende tags YAML custom como `!GetAtt`, así que hay que escribir el equivalente en YAML plano.
- **Firma**: `handler(event, context)` — sin `@handle_exceptions` (no es HTTP); maneja `commit`/`rollback` manualmente.
- **Flujo**: es el "safety net" de 15 minutos (`SIGNING_WINDOW`) encolado por `create_signature`. Por cada `record` del batch SQS: parsea `signature_id` del body; busca la fila; si no existe, solo loguea `WARNING` y sigue; si el `stage` ya está en `_SKIP_STAGES = (SIGNED, FAILED, SIGNING)`, no hace nada (deliberado: `SIGNING` lo vigila el otro worker, `check_signing_timeout`, para no competir por la misma fila); en cualquier otro caso, marca la fila `FAILED` con `Signatures.mark_failed` y agrega el `signature_id` a una lista local `newly_failed`. Cada excepción por record se captura y se loguea sin abortar el batch completo. Al final del batch: un único `db_session.commit()` (comentario: las notificaciones solo deben disparar **después** de que el commit tuvo éxito, para no notificar un `FAILED` que en realidad no llegó a persistirse); luego, para cada `signature_id` en `newly_failed`, llama `notify_terminal_state(signature_id, "FAILED")`.
- **Clases/métodos usados**: `Signatures.get_by_id/mark_failed`, `SignatureStage`; `notify_terminal_state`; `db_session` (`libs/core/db.py`).

#### `src/workers/check_signing_timeout`

- **Trigger**: evento SQS sobre `Fn::GetAtt: [SigningTimeoutQueue, Arn]`, `batchSize: 5`, `timeout: 30` (mismo comentario sobre `js-yaml` y la forma larga de `Fn::GetAtt`).
- **Firma**: `handler(event, context)`.
- **Flujo**: análogo a `check_signature_timeout`, pero para la ventana corta de 60s (`SIGNING_TIMEOUT`) encolada por `resolve_otp` justo al despachar `sign_doc`. Solo actúa si el `stage` sigue siendo exactamente `SIGNING` (si ya es `SIGNED`/`FAILED`, no toca nada); si sigue en `SIGNING` significa que `sign_doc` nunca completó a tiempo (crasheó, colgó, o no llegó a invocarse), y lo marca `FAILED`. El comentario del handler aclara una decisión de diseño importante: **`sign_doc` nunca se marca `FAILED` a sí mismo** por sus propios errores internos (un fallo interno del pipeline de firma no es "culpa" del firmante); este worker es el único mecanismo que decide que, para esta etapa, la firma falló.
- **Clases/métodos usados**: `Signatures.get_by_id/mark_failed`, `SignatureStage`; `notify_terminal_state`; `db_session`.

#### `src/workers/notify_signed`

- **Trigger**: invocación directa (sin HTTP, sin SQS) — disparada por `notify_terminal_state(signature_id, "SIGNED", notify_signer=True)`, que solo `sign_doc` llama con `notify_signer=True`.
- **Firma**: `handler(event, context)`.
- **Flujo**: lee `signature_id` del payload; busca la fila; si no está en `stage=SIGNED` o no tiene `signed_s3_key`, loguea `WARNING` y sale (`skipped=True`) — defensivo contra una invocación fuera de orden; si no hay `email` en la fila, loguea `WARNING` y sale; genera una URL presignada de descarga del `signed_s3_key` con `presign_download`; renderiza el correo con `render_signed_email` (`libs/utils/signed_email.py`) y lo envía con `send_email`. Es *best-effort* explícito: el comentario del módulo aclara que un fallo del mailer aquí nunca debe afectar el estado de la firma, que ya es terminal (`SIGNED`) para el momento en que este worker corre.
- **Clases/métodos usados**: `Signatures.get_by_id`, `SignatureStage`; `presign_download`; `render_signed_email`; `send_email`.

#### `src/workers/sign_doc`

- **Trigger**: invocación asíncrona directa (`InvocationType=Event`), disparada únicamente por `resolve_otp` tras validar el OTP correctamente. `memorySize: 2048`, `timeout: 300` (overrides propios en su `function.yml` sobre los defaults del `provider`) — acorde al comentario: el costo computacional está en la emisión de certificado RSA y en la firma PAdES.
- **Firma**: `handler(event, context)`.
- **Flujo**: lee `signature_id` del payload (si falta, loguea `ERROR` y devuelve `{"ok": False, "error": "missing_signature_id"}`); busca la fila (si no existe, análogo con `signature_not_found`); si el `stage` no es exactamente `SIGNING`, loguea `WARNING` y devuelve `{"ok": False, "skipped": True, "stage": ...}` — esto hace la invocación **idempotente** frente a reintentos manuales (p. ej. un `aws lambda invoke` repetido no vuelve a firmar algo ya firmado ni corrompe una fila ya fallida). Si todo procede, llama a `_run_pipeline(row)`:
  1. Descarga de S3 el PDF original (`doc_s3_key`), el PNG/binario de la firma dibujada (`draw_s3_key`) y las tres evidencias biométricas (`id_front_s3_key`, `id_back_s3_key`, `id_face_s3_key`).
  2. Para **cada** ubicación en `row.sign_location` (es una lista, no una sola ubicación), llama `stamp_drawing_on_pdf(stamped_pdf, draw_png, location)` — soporta estampar la misma firma manuscrita en varias posiciones/páginas del documento.
  3. Emite el certificado de transacción con `issue_transaction_cert(signature_id=row.id, signer_email=row.email, signer_name=row.signatory)` → `(cert_pem, key_pem, cert_serial)`.
  4. Calcula `doc_hash = sha256(stamped_pdf)` y captura `signed_at = now(UTC)`.
  5. Construye la página de auditoría con `build_audit_page(...)`, pasándole las cuatro imágenes de evidencia, el `cert_serial`, el `doc_hash` y el `signing_data` (la telemetría de IP/user-agent capturada por `resolve_otp`).
  6. Anexa esa página al PDF estampado con `_append_page` (función local del propio handler, basada en `pypdf.PdfWriter.append`), produciendo `combined_pdf` — el comentario del módulo `signature_audit_page.py` aclara que esto **debe** ocurrir antes de firmar, porque PAdES solo cubre los bytes que existían al momento de la firma; cualquier página anexada después haría que el documento se lea como manipulado.
  7. Firma `combined_pdf` con `sign_pdf_pades_b(combined_pdf, cert_pem, key_pem)` → `signed_pdf`; calcula `signed_hash = sha256(signed_pdf)`.
  8. Sube dos objetos a S3: `raw_signed.pdf` (el `stamped_pdf` combinado, **sin** firmar — su hash es justamente `doc_hash`, el valor impreso dentro del PDF ya firmado) y `signed.pdf` (el resultado final firmado).
  9. Marca la fila `SIGNED` con `Signatures.mark_signed(signed_s3_key, raw_signed_s3_key, doc_hash, signed_hash, signed_at)`.
  - Tras `_run_pipeline`, el handler hace `db_session.commit()`, loguea `INFO` y llama `notify_terminal_state(signature_id, "SIGNED", notify_signer=True)` (dispara tanto `sign_trigger` como `notify_signed`). Si `_run_pipeline` lanza cualquier excepción, el handler la captura, loguea `ERROR`, hace `db_session.rollback()` y devuelve `{"ok": False, "error": "internal_error"}` — **no** marca la fila `FAILED` él mismo (esa responsabilidad es de `check_signing_timeout`, como se documentó arriba); un `finally` cierra la sesión.
- **Clases/métodos usados**: `Signatures.get_by_id/mark_signed`, `SignatureStage`; `download_bytes/upload_from_bytes` (`libs/core/s3.py`); `stamp_drawing_on_pdf` (`libs/utils/signature_stamp.py`); `issue_transaction_cert/sign_pdf_pades_b` (`libs/utils/signature_ca.py`); `build_audit_page` (`libs/utils/signature_audit_page.py`); `notify_terminal_state`; `PdfReader/PdfWriter` (`pypdf`) vía la función local `_append_page`.

#### `src/workers/sign_trigger`

- **Trigger**: invocación asíncrona directa, disparada por `notify_terminal_state` desde cuatro orígenes: `sign_doc` (stage `SIGNED`), y `resolve_otp` / `check_signature_timeout` / `check_signing_timeout` (stage `FAILED`).
- **Firma**: `handler(event, context)`.
- **Flujo**: valida que el payload traiga `signature_id` y `stage` en `("SIGNED", "FAILED")` (si no, `ERROR` + `{"ok": False, "error": "bad_payload"}`); resuelve la URL del webhook con `_load_webhook_url()`, que lee una vez por contenedor (`_webhook_url_loaded` como caché de nivel de módulo) el parámetro SSM `SSM_SIGN_TRIGGER_PATH`; si el parámetro no está provisto o falla la lectura, cachea `None` y cualquier invocación futura en ese contenedor cálido simplemente loguea `WARNING` y responde `{"ok": False, "skipped": True}` — mismo patrón "desactivado por ausencia" que el resto de features opcionales del servicio; si hay URL, hace `requests.post(webhook_url, json={"signature_id": ..., "stage": ...}, timeout=10)`; cualquier excepción de red se traduce a `{"ok": False, "error": "webhook_unreachable"}`; un status fuera de 2xx se traduce a `{"ok": False, "error": f"webhook_status_{code}"}`.
- El comentario de cabecera del módulo aclara una diferencia de diseño respecto al servicio legado: este webhook **no** es por-firma (no hay columna `callback_url` en la tabla `Signatures` actual) sino un único endpoint fijo para todo el proyecto, leído de SSM.
- **Clases/métodos usados**: ninguno de `libs/orm` (no toca la DB); `boto3` directo para SSM; `requests` para el POST; `Logger`.

### Clases y métodos de dominio propios del servicio

A diferencia de lo que podría esperarse por analogía con `_legacy/utils/` (que sí tenía una carpeta `utils/` local dentro de `services/signatures/` con `evidence.py`, `mock_ca.py` y `evidence_package.py`), **el código activo del servicio no tiene una carpeta `utils/` propia**: `services/signatures/` solo contiene `src/` (con `handlers/` y `workers/`) y `_legacy/`. Toda la lógica de dominio de firma digital que cumpliría ese rol hoy vive en `backend/libs/utils/`, es decir, en la carpeta de utilidades **compartida** del backend — pero son módulos cuyo contenido es exclusivamente de dominio de firma digital (no se usan desde ningún otro servicio del backend salvo `signatures`), así que se documentan aquí como el equivalente real de ese "utils de dominio":

- **`libs/utils/signature_ca.py`** — Entidad Certificadora mock, puerto desde `_legacy/utils/mock_ca.py` "recortado a las dos operaciones que `sign_doc` necesita" (según su propio docstring); no incluye verificación de cadena de confianza, porque no hay endpoint `/verify` activo.
  - `_load_root_ca() -> tuple[bytes, bytes]`: lee de SSM (`WithDecryption=True`) los dos `SecureString` `/cdts/{stage}/mock-ca/root/{cert-pem,private-key-pem}`; cachea el resultado en la variable de módulo `_root_ca_cache` (persiste entre invocaciones de un contenedor cálido); lanza `RuntimeError` si `STAGE` no está seteado o si SSM falla.
  - `_pem_to_der`, `_to_asn1_cert`, `_to_asn1_key`, `_cryptography_private_key_from_pem`, `_cryptography_cert_from_pem`: helpers privados de conversión de formato entre PEM, DER y los objetos que esperan `asn1crypto` (para `pyhanko`) y `cryptography` (para construir certificados).
  - `issue_transaction_cert(signature_id, signer_email, signer_name=None, valid_hours=1) -> tuple[cert_pem, key_pem, serial_hex]`: genera un par RSA-2048 nuevo (`rsa.generate_private_key`); construye un certificado leaf X.509 con `CommonName` = nombre del firmante (o su email si no hay nombre, truncado a 64 chars), `emailAddress` y una `OrganizationalUnitName` igual al `signature_id` (trunco a 64 chars); serial aleatorio de 128 bits (`secrets.token_bytes(16)`); extensiones `BasicConstraints(ca=False)`, `KeyUsage` (firma digital + "non-repudiation"/`content_commitment`, sin cifrado) y `SubjectAlternativeName` con el email; firma el certificado con la llave privada de la CA raíz (`root_key`) usando SHA-256; devuelve el PEM del certificado, el PEM de la llave privada (PKCS8, sin cifrar) y el serial en hex. La llave privada del leaf **nunca se persiste**: vive solo en la memoria de la invocación de `sign_doc` que la generó y la usa inmediatamente para firmar.
  - `_build_signer(cert_pem, private_key_pem) -> SimpleSigner`: registra la CA raíz en un `SimpleCertificateStore` (de `pyhanko_certvalidator`) y construye un `SimpleSigner` de `pyhanko` con el certificado/llave del leaf.
  - `sign_pdf_pades_b(pdf_bytes, cert_pem, private_key_pem, *, reason="Digital signature via CDTs Mock CA", location=None) -> bytes`: crea un campo de firma invisible llamado `CDTsSignature1` (`SigFieldSpec` + `append_signature_field`) sobre un `IncrementalPdfFileWriter`; firma con `PdfSigner`/`PdfSignatureMetadata` (`md_algorithm="sha256"`) produciendo una firma **PAdES-B baseline**. El docstring aclara por qué el campo es invisible: el garabato del firmante, ya estampado visualmente por `signature_stamp.py`, es la affordance visual; PAdES-B es válida sin necesidad de un widget visible, y los lectores de PDF igual muestran el panel de firmas.

- **`libs/utils/signature_stamp.py`** — overlay del garabato sobre el PDF, puerto desde `_legacy/utils/stamp.py`.
  - `stamp_drawing_on_pdf(pdf_bytes, drawing_png, sign_location: dict) -> bytes`: recibe un diccionario `{"page": int (1-indexado), "x_pct", "y_pct", "width_pct"?, "height_pct"?}` (porcentajes 0–100, con `x_pct`/`y_pct` medidos desde la esquina **superior**-izquierda, convención amigable para UI); valida que `page` esté en rango de páginas del PDF; calcula el ancho de la caja de destino a partir de `width_pct` (default 25%); si no viene `height_pct`, lo deriva preservando el aspect ratio de la imagen del garabato; convierte las coordenadas "desde arriba" de la UI a coordenadas PDF (origen inferior-izquierdo): `ury = page_h - page_h*(y_pct/100)`, `lly = ury - box_h`; dibuja la imagen sobre un canvas de `reportlab` del mismo tamaño que la página, con `mask="auto"` (respeta el canal alfa del PNG); mergea ese canvas como overlay sobre la página objetivo con `pypdf`'s `page.merge_page`; devuelve el PDF completo reescrito. No es idempotente (llamarla dos veces estampa dos veces) — por eso `sign_doc` la llama una vez por cada elemento de `sign_location` y no en un loop repetido sobre el mismo PDF ya estampado.

- **`libs/utils/biometrics.py`** — validadores Rekognition para la etapa `BIOMETRICS`, puerto simplificado desde `_legacy/utils/evidence.py` ("ya no hay necesidad de probar extensiones candidatas porque el flujo nuevo ya sabe exactamente a qué key subió", según su docstring).
  - `_check_size(bucket, key) -> tuple[bool,str] | None`: hace `head_object`; devuelve `(False, "evidence_missing")` si S3 responde 404/`NotFound`, `(False, "evidence_too_large")` si supera 5 MiB (límite de Rekognition por request), o `None` si está todo bien (para que el caller siga).
  - `_detect_text_lines(bucket, key) -> list[dict]`: llama `rekognition.detect_text` sobre la referencia `S3Object` y filtra solo las detecciones de `Type == "LINE"`.
  - `analyze_id_front(bucket, key) -> (bool, str)`: exige al menos 3 líneas de texto con confianza ≥70%, y al menos 6 dígitos en total sumando esas líneas (heurística de "hay un número de documento legible"); razones posibles: `evidence_missing`, `evidence_too_large`, `too_few_legible_lines`, `no_id_number_detected`, `ok`.
  - `analyze_id_back(bucket, key) -> (bool, str)`: igual pero más laxo — solo exige 2 líneas legibles, sin chequeo de dígitos.
  - `analyze_face(bucket, key) -> (bool, str)`: llama `rekognition.detect_faces` con `Attributes=["EYES_OPEN"]`; exige exactamente 1 cara detectada (0 → `no_face_detected`, >1 → `multiple_faces`), confianza de la cara ≥90% (`low_confidence`), y ojos abiertos con confianza ≥80% (`eyes_closed`). Ninguna de las tres funciones lanza excepción por una foto inválida — devuelven `(False, razón)`, porque ese es un resultado de negocio normal que `set_biometrics` reporta al front, no un error de servidor.

- **`libs/utils/signature_audit_page.py`** — construcción de la página de evidencia/auditoría que se anexa al PDF antes de firmarlo.
  - Carga tres fuentes TTF (IBM Plex Sans Regular/SemiBold y Plex Mono, licencia SIL OFL 1.1) una sola vez por módulo, registrándolas en `reportlab.pdfbase.pdfmetrics` solo si no están ya registradas.
  - Funciones privadas de layout (`_y`, `_spaced`, `_eyebrow`, `_section_title`, `_format_date`, `_format_resolved_at`, `_draw_cell`, `_status_pill`, `_data_row`): todas trabajan con un sistema de coordenadas "de arriba hacia abajo" (`_y(top)` convierte a la convención bottom-left real de PDF) para que el layout se escriba en el orden natural en que se lee.
  - `build_audit_page(*, signature_id, signatory, email, id_front_png, id_back_png, face_png, draw_png, signed_at, cert_serial, document_hash, signing_data) -> bytes`: genera una única página tamaño Letter con: encabezado + pill "FIRMADO"; tarjeta con nombre/email del firmante y fecha/hora de firma; una grilla 2×2 con las cuatro imágenes de evidencia (documento de identidad frente/reverso, selfie, firma dibujada) — cada celda se escala preservando aspect ratio dentro de un cuadro fijo; una sección de "datos técnicos" con el ID de la firma, el serial del certificado, el hash SHA-256 (mono-espaciado), una frase de verificación que menciona el OTP y, si está disponible, la fecha/hora de validación (`signing_data["resolved_at"]`), la IP, el user-agent y el idioma del navegador capturados por `resolve_otp`; y un footer que aclara que el hash impreso corresponde al documento **sin** esta página de evidencia (el `raw_signed.pdf`), y que el proyecto es académico "sin validez jurídica". El docstring del módulo insiste en que esta página debe generarse e incorporarse al PDF **antes** de aplicar la firma PAdES, porque la firma solo protege los bytes que existían en ese momento.

- **`libs/utils/signature_notifications.py`** — punto único de disparo de notificaciones post-firma, para evitar que los cuatro call sites que llegan a un estado terminal (`sign_doc`, `resolve_otp`, `check_signature_timeout`, `check_signing_timeout`) diverjan entre sí.
  - `notify_terminal_state(signature_id, stage: str, *, notify_signer: bool=False) -> None`: siempre invoca de forma asíncrona `sign_trigger` con `{"signature_id", "stage"}`; si `notify_signer=True` (solo lo pasa `sign_doc`, y solo para `"SIGNED"`), además invoca asíncronamente `notify_signed`. Cualquier `LambdaInvokeError` al **enviar** la invocación se loguea como `ERROR` pero nunca se relanza — la transición de estado de la firma (ya comiteada en la DB) no debe revertirse por un problema de "plumbing" de notificaciones.

- **`libs/utils/otp_email.py`** — `render_otp_email(*, otp, signatory, issued_at, ttl, signature_id) -> (subject, html)`: renderiza un template HTML inline (sin motor de templates externo, solo `str.format`) con el código de 6 dígitos, el saludo (nombre del firmante o "there"), la hora de expiración calculada como `issued_at + ttl`, y los primeros 8 caracteres del `signature_id` como referencia visible. El docstring aclara que el correo deliberadamente no incluye ningún link, porque el firmante ya tiene abierta la sesión desde la que pidió el código.

- **`libs/utils/signed_email.py`** — `render_signed_email(*, signatory, signed_at, signed_url, signature_id) -> (subject, html)`: renderiza (en español) el correo de "firmaste un documento", con un botón que apunta a `signed_url` (una URL presignada, no un adjunto — el docstring señala que `mailer.send_email` no soporta adjuntos, y un link mantiene el correo liviano sin importar el tamaño del PDF).

- **`libs/utils/lambda_invoke.py`** — helper de invocación Lambda-a-Lambda, usado transversalmente por el servicio (no es exclusivo de `signatures`, pero es el mecanismo que conecta todos sus workers entre sí).
  - `resolve_function_name(service, function_key, stage=None) -> str`: reconstruye el nombre convencional `cdts-{stage}-{service}-{function_key-con-guiones}`, igual a la convención de `build-functions.js`; `service=None` cae al env var `SERVICE` (para `signatures`, literalmente `"signatures"`); lanza `RuntimeError` si no puede resolver `service` o `stage` en vez de adivinar.
  - `invoke_sync(function_key, payload=None, *, service=None) -> dict`: invoca con `InvocationType="RequestResponse"` y espera la respuesta; lanza `LambdaInvokeError` con `error_type` en `{"boto_error","bad_status","bad_payload","function_error"}` según dónde falle. No se usa activamente dentro de `signatures` (los workers internos se comunican todos vía `invoke_async`), pero está disponible.
  - `invoke_async(function_key, payload=None, *, service=None) -> None`: invoca con `InvocationType="Event"` (fire-and-forget); solo observa si la **sumisión** fue aceptada (`StatusCode==202`); el resultado real de la Lambda invocada nunca se conoce desde el caller. Es el mecanismo real detrás de `resolve_otp → sign_doc` y de `notify_terminal_state → sign_trigger / notify_signed`.
  - `LambdaInvokeError(function_name, error_type, detail)`: excepción con atributos estructurados para que el caller decida cómo reaccionar sin parsear el mensaje.

- **`libs/utils/validators.py`** — usado por `set_signature_form` únicamente: `valid_email(value) -> bool` (regex simple `^[^@\s]+@[^@\s]+\.[^@\s]+$` + longitud ≤320); también define `password_reason`, que no se usa en ningún handler de `signatures` (pertenece a otro dominio del backend, probablemente `auth`).

Por último, el modelo de persistencia del dominio, `libs/orm/signatures.py`, aunque formalmente vive en `libs/orm/` (compartida), es en la práctica la clase de dominio central del servicio: define las constantes `SIGNING_WINDOW` (15 min), `OTP_TTL` (2 min), `MAX_OTP_TRIES` (3) y `SIGNING_TIMEOUT` (60s); los enums `SignatureStage` y `BiometricType`; el mapeo `BIOMETRIC_COLUMNS` (de `BiometricType` a nombre de columna); y la clase `Signatures(Base)` con todos los métodos de transición de estado usados por los handlers y workers arriba documentados (`create`, `get_by_id`, `set_email`, `set_biometric_key`, `advance_to_signature_stage`, `set_draw_key`, `set_otp`, `register_failed_otp_attempt`, `start_signing`, `mark_signed`, `mark_failed`) — cada uno de ellos es, en esencia, un `UPDATE ... RETURNING` de SQLAlchemy ejecutado a través del singleton `db_session` (`libs/core/db.py`), nunca una mutación en memoria del objeto.

---

## 7. Librerías compartidas (`backend/libs/`)

`backend/libs/` es el paquete Python compartido por los 7 microservicios del monorepo. No es un servicio desplegable en sí mismo: Serverless Framework empaqueta estos módulos junto con el código de cada handler porque cada bloque (`services/<svc>/serverless.yml`) incluye `backend/libs/` dentro de su `package.patterns` (o equivalente), de modo que en tiempo de ejecución Lambda puede hacer `from libs.core... import ...` exactamente igual que en los tests locales. Contiene 29 archivos `.py` repartidos en tres subcarpetas: `core/` (6 archivos), `orm/` (12 archivos) y `utils/` (14 archivos más el paquete de fuentes `fonts/` usado por `signature_audit_page.py`).

### 7.1 `libs/core/` -- infraestructura base

#### `db.py` -- sesión SQLAlchemy a Postgres vía SSM

Al importarse (efecto de módulo, no perezoso) llama a `_load_db_config()`, que hace `boto3.client("ssm").get_parameters_by_path(Path=SSM_DB_PATH, WithDecryption=True)` sobre `SSM_DB_PATH = /cdts/{STAGE}/db` (con `STAGE` tomado de la variable de entorno `STAGE`, default `"dev"`) y construye un diccionario `{host, port, name, user, password, ...}` a partir del último segmento del nombre de cada parámetro. Con ese diccionario crea el `engine` de SQLAlchemy (`postgresql+pg8000://user:password@host:port/name`, `pool_pre_ping=True`, `pool_recycle=840`). Un listener `@event.listens_for(engine, "connect")` ejecuta `SET search_path TO {STAGE}, pg_catalog` en cada conexión nueva — así todas las tablas definidas en `libs/orm` (sin schema explícito) resuelven contra el schema del stage activo (`dev`, `pro`, `test`, etc.) sin que cada modelo tenga que calificarlo.

- **`Session`**: `sessionmaker(bind=engine)`.
- **`class DBSession`** (singleton vía `__new__`): envuelve una única `Session()` por contenedor Lambda cálido.
  - `query(*, statement, many=False)`: ejecuta `self.session.execute(statement).scalars()`; si `many=True` devuelve `list(result)`, si no devuelve `result.first()` (o `None`). Es el método que usan **todos** los modelos ORM para correr sus `select`/`insert`/`update`.
  - `commit()` / `rollback()` / `close()`: delegan al método homónimo de la sesión interna.
- **`db_session`**: instancia module-level del singleton, importada por `libs/orm/*` y por `libs/core/responses.py`.

Al ser singleton con estado mutable en un contenedor Lambda reutilizado entre invocaciones (warm start), es crítico cerrar explícitamente la sesión al final de cada invocación — lo que hace `responses.handle_exceptions` (ver abajo) en su bloque `finally`.

Consumido (indirectamente, a través de cada modelo ORM) por **files, processes, signatures** y, de forma transitiva, por cualquier handler que importe un modelo de `libs/orm`.

#### `logger.py` -- logging mínimo

`Logger.log(level: str, message)`: resuelve `getattr(_logger, level.lower(), _logger.info)` sobre el logger raíz de `logging` (configurado a nivel `INFO`) y lo invoca con `message`. Es el único punto de logging usado en todo `libs/`; nunca lanza si `level` no es un nombre válido (cae a `info`). Usado por `files`, `processes`, `signatures` directamente, y de forma transitiva por casi cualquier módulo de `libs/utils` que loguea advertencias/errores (`auth.py`, `lambda_invoke.py`, `mailer.py`, `signature_ca.py`, `signature_notifications.py`).

#### `mailer.py` -- envío de correo transaccional por SMTP

Credenciales SMTP en SSM bajo `/cdts/{STAGE}/smtp/user` (String) y `/cdts/{STAGE}/smtp/password` (SecureString), cacheadas de forma perezosa (`_load_creds`, con flag `_creds_loaded` para no reintentar en cada llamada aunque la primera carga falle).

- `is_configured() -> bool`: `True` si las credenciales SMTP pudieron cargarse.
- `send_email(to: str, subject: str, html: str) -> bool`: construye un `EmailMessage` (texto plano de fallback + alternativa HTML) y lo envía por `smtplib.SMTP_SSL` contra `SMTP_HOST`/`SMTP_PORT` (default `smtp.gmail.com:465`). **Nunca lanza**: cualquier excepción (credenciales ausentes, fallo SMTP) se loguea y la función devuelve `False`. Esto es deliberado según el docstring del módulo: un correo que no sale no debe revertir trabajo de base de datos ya confirmado; el llamador decide si ofrece un canal alternativo.

Usado por **signatures** (para el OTP de firma y el correo de "documento firmado").

#### `responses.py` -- helpers de respuesta HTTP y manejo de errores

- `generate_response(body=None, status_code=200, headers=None) -> dict`: devuelve el formato de respuesta de API Gateway/Lambda proxy integration (`statusCode`, `headers` con `Content-Type: application/json` por defecto, `body` serializado con `json.dumps(..., default=str)` para tolerar `Decimal`/`UUID`/`datetime`).
- `class HandledError(Exception)`: excepción de negocio con `message` y `status_code` (default 400); es el mecanismo estándar para que un handler aborte con un código HTTP específico sin tener que construir la respuesta a mano.
- `handle_exceptions(func)`: decorador que envuelve un handler Lambda `(event, context) -> dict`. Ejecuta `func`, y si no hay excepción hace `db_session.commit()` y devuelve la respuesta. Si se lanza `HandledError`, hace `rollback()`, loguea `WARNING` y devuelve `generate_response({"error": e.message}, e.status_code)`. Cualquier otra excepción hace `rollback()`, loguea `ERROR` con traceback completo y devuelve un 500 genérico (`{"error": "internal_server_error"}`) — nunca filtra el mensaje interno al cliente. En un bloque `finally` siempre llama `db_session.close()`, con el comentario explícito de que, al ser la sesión un singleton que sobrevive entre invocaciones en un contenedor cálido, omitir el cierre dejaría la transacción abierta y las invocaciones siguientes leerían el mismo snapshot, sin ver filas comprometidas por otro servicio.

Es el decorador externo que envuelve casi cada handler HTTP (junto con `require_auth` de `libs/utils/auth.py`). Usado por **auth, banks, files, forms, processes, signatures**.

#### `s3.py` -- helpers de S3 entre servicios

Cliente módulo-level `boto3.client("s3", config=Config(signature_version="s3v4"))`.

- `upload_from_bytes(bucket, key, data, content_type=None) -> None`: `put_object` directo.
- `presign_upload(bucket, key, content_type, metadata=None, expires=900) -> str`: URL presignada para `PUT` directo desde el navegador; si se pasan `metadata`, éstas quedan firmadas en la URL y el cliente debe reenviarlas como cabeceras `x-amz-meta-<key>` idénticas o S3 rechaza el `PUT`.
- `presign_download(bucket, key, expires=900, filename=None) -> str`: URL presignada de `GET`; si se pasa `filename`, fija `ResponseContentDisposition` para forzar descarga con ese nombre.
- `head_object(bucket, key) -> dict`: metadatos del objeto sin descargarlo.
- `download_bytes(bucket, key) -> bytes`: lee el objeto completo en memoria.

Usado por **files** (subida/descarga de documentos del proceso) y **signatures** (biometría, PDF firmado).

#### `sqs.py` -- wrapper mínimo de SQS

Única función: `send_message(queue_url, body: str, delay_seconds: int = 0) -> None`, que envuelve `boto3.client("sqs").send_message`. Usado por **signatures** para encolar los workers de timeout (`check_signature_timeout`, `check_signing_timeout`) con `DelaySeconds` sincronizado con las constantes `SIGNING_WINDOW`/`SIGNING_TIMEOUT` de `libs/orm/signatures.py`.

---

### 7.2 `libs/orm/` -- modelos de datos (SQLAlchemy)

Todos los modelos siguen el mismo patrón: usan `Mapped[...]`/`mapped_column` de SQLAlchemy 2.x, exponen métodos de consulta/mutación como funciones "estilo estático" definidas dentro de la clase (no decoradas con `@staticmethod`, por lo que se invocan como `Modelo.metodo(args)` y no sobre una instancia), construyen un `select`/`insert`/`update` de SQLAlchemy Core y lo ejecutan a través de `db_session.query(statement=...)`. Ninguno abre conexión directamente: toda la E/S pasa por el singleton de `libs/core/db.py`.

#### `base.py` -- base declarativa común

`class Base(DeclarativeBase)`: única clase base de la que heredan todos los modelos. Define un solo método común, `to_dict() -> dict`, que copia `self.__dict__` descartando atributos privados (prefijo `_`, p.ej. el estado interno de SQLAlchemy) y serializa `datetime` a ISO-8601 (`.isoformat()`) y `UUID` a `str`. No hay mixins adicionales (de auditoría, soft-delete, etc.) — cada modelo declara sus propias columnas `created_at`/`updated_at` cuando las necesita.

#### `__init__.py` -- registro de todos los modelos

No expone utilidades propias; su único propósito es **importar todos los modelos** para que SQLAlchemy pueda resolver los `ForeignKey` cruzados entre tablas. El docstring lo explica: un mapper sólo "ve" las tablas registradas en `Base.metadata`; si un handler importa únicamente `Processes` (que declara `ForeignKey("banks.id")`), SQLAlchemy lanzaría `NoReferencedTableError` porque `banks` nunca se registró. Importar el paquete (`from libs.orm import Users, ...` o simplemente dejar que `__init__.py` se ejecute) resuelve esto. El orden de los imports sigue las dependencias FK para legibilidad (`Users → UserCredentials → Banks → TermBand → AmountBand → Rate → BearerTokens → Forms → Processes → Files → Signatures`), aunque SQLAlchemy resuelve las referencias de forma perezosa. Exporta explícitamente los 11 modelos vía `__all__` (más `Base`).

#### `banks.py` -- tabla `banks`

Columnas: `id` (PK, int), `code`, `name`, `logo_key`, `io_key` (nullable), `description`, `tier`, `rating_by`, `highlights` (`ARRAY(Text)`), `is_active` (bool), `created_at`, `updated_at`. Sin relaciones declaradas explícitamente (las FK hacia `banks.id` viven en `rates_amount_band`/`rates_term_band`/`processes`, pero sin `relationship()` ORM — se consultan por `bank_id` suelto).

- `get_all(active=None)`: `select` ordenado por `(tier, name)`; si se pasa `active`, filtra por `is_active`. Devuelve lista (`many=True`).
- `get_by_id(bank_id)`: `select ... limit(1)`, devuelve una fila o `None`.

Usado por el servicio **banks** (listado/detalle de bancos) y leído también desde **processes** (para resolver datos del banco asociado a un proceso).

#### `bearer_tokens.py` -- tabla `bearer_tokens`

Columnas: `id` (PK, UUID), `user_id` (UUID), `token_hash` (string, SHA-256 hex del token plano), `expires_at`, `revoked_at`, `created_at`.

- `create(user_id, token_hash, expires_at)`: `insert ... returning(BearerTokens)`.
- `get_by_hash(token_hash)`: `select ... where token_hash == ... limit(1)`.
- `update_by_id(id, values)`: `update ... where id == ... values(**values) returning(...)` — genérico, usado para marcar `revoked_at`.

No se referencia directamente desde `services/*` (no hay `from libs.orm.bearer_tokens import` en los handlers), sino siempre a través de `libs/utils/auth.py` (`issue_token`, `require_auth`) y `libs/utils/bearer_tokens.py` (`is_alive`, `revoke`), que sí son consumidos por el servicio **auth** y, mediante `require_auth`, por todos los servicios protegidos (**auth, files, forms, processes**).

#### `files.py` -- tabla `files`

Incluye el enum `FileType` (`TAX_DECLARATION`, `RUT`, `BANK_CERT`, `INVESTMENT_ORDER`). Columnas: `id` (PK UUID), `process_id` (UUID), `file_type` (string 50), `s3_key` (Text, `unique`), `original_name` (opcional), `size_bytes` (opcional, `BigInteger`), `content_type` (opcional), `uploaded_at` (con zona horaria).

- `create(process_id, file_type, s3_key, original_name=None, size_bytes=None, content_type=None)`: `insert ... returning(Files)`.
- `list_by_process(process_id)`: `select ... where process_id == ... order_by(uploaded_at.desc())`, `many=True`.

Usado por **files** (registro de documentos subidos) y **processes** (para listar archivos de un proceso).

#### `forms.py` -- tabla `forms` (datos del formulario KYC, 1:1 con el usuario)

Incluye cuatro enums de dominio: `DocumentType` (`CC, CE, TI, PA`), `GenderType` (`M, F, O`), `CivilStatusType` (`SINGLE, MARRIED, DIVORCED, WIDOWED`), `EducationLevelType` (`NONE` … `POSTGRADUATE`). La PK es directamente `user_id` (UUID) — no hay `id` propio, el formulario es 1:1 con `users`. Columnas extensas de datos personales (nombre, nacimiento, ubicación, documento, contacto, estado civil, nivel educativo) y financieras (`monthly_income`, `monthly_expenses`, `total_assets`, `total_liabilities`, `is_tax_declarant`, `is_pep`), todas opcionales salvo `document_type`/`document_number`. `created_at`/`updated_at` usan `server_default=text("NOW()")`.

- `upsert(cls, user_id: UUID, **fields)` (classmethod): usa `pg_insert(cls).values(...).on_conflict_do_update(index_elements=["user_id"], set_={**fields, "updated_at": text("NOW()")})` — es decir, un upsert real a nivel de Postgres (`INSERT ... ON CONFLICT DO UPDATE`), no un `select`+`update` en dos pasos.
- `get_by_user_id(cls, user_id)` (classmethod): `select ... where user_id == ... limit(1)`.

Usado exclusivamente por **forms**.

#### `processes.py` -- tabla `processes` (el proceso de solicitud de CDT)

Enum `ProcessStage`: `FORM → DOCUMENTS → SIGNATURE → PAYMENT → REVIEW → SENT_TO_BANK → COMPLETED`. Columnas: `id` (PK UUID, `default=uuid4`), `user_id`, `bank_id` (int), `amount` (`Numeric(15,2)`), `term` (int, días), `rate` (`Numeric(5,2)`), `stage` (string), `submitted_form` (JSONB opcional, snapshot del formulario al momento de avanzar a DOCUMENTS), `signature_id` (UUID opcional, enlaza con `signatures.id`), `created_at`, `updated_at`.

- `create(user_id, bank_id, amount, term, rate)`: inserta con `stage=FORM`.
- `get_by_id(process_id)` / `list_by_user(user_id)` (ordenado por `created_at.desc()`, `many=True`).
- `set_submitted_form(process_id, submitted_form)`: `update` que fija `submitted_form`, avanza `stage=DOCUMENTS` y toca `updated_at=NOW()`.
- `set_signature_id(process_id, signature_id)`: `update` que fija `signature_id`, avanza `stage=SIGNATURE` y toca `updated_at`.

Todos los métodos de mutación devuelven la fila actualizada (`returning(Processes)`). Usado por **processes** (dueño) y leído por **files** (para validar que un `process_id` existe antes de aceptar un archivo).

#### `rates.py` -- tabla `rate` (tasa por combinación de bandas)

PK compuesta (`term_band_id`, `amount_band_id`), columna `rate` (`Numeric(5,2)`).

- `get_by_bands(amount_band_id, term_band_id)`: tasa exacta para un par de bandas, o `None`.
- `get_all_by_bands(band_pairs)`: dado una lista de pares `(amount_band_id, term_band_id)`, hace un `join` con `TermBand` para resolver `bank_id` y devuelve `[(bank_id, rate), ...]` ordenado por tasa descendente (mejor tasa primero). Nota de implementación: esta función usa `db_session.session.execute(...).all()` directamente en vez de pasar por `db_session.query(...)`, porque necesita filas con columnas mixtas (`TermBand.bank_id`, `Rate.rate`) en vez de instancias de un único modelo ORM.

No se usa directamente desde `services/*`; se consume siempre a través de `libs/utils/rates.get_ranked_rates`, que sí usa el servicio **banks** para el simulador de tasas.

#### `rates_amount_band.py` -- tabla `rates_amount_band`

Columnas: `id` (PK), `bank_id`, `min_amount`, `max_amount` (`Numeric(15,2)`).

- `get_by_bank_amount(bank_id, amount)`: la banda (si existe) de ese banco que cubre `amount`.
- `get_all_by_amount(amount)`: todas las bandas (a lo sumo una por banco) que cubren `amount`, `many=True`.

Igual que `rates.py`, se consume indirectamente vía `libs/utils/rates.get_ranked_rates` (servicio **banks**).

#### `rates_term_band.py` -- tabla `rates_term_band`

Simétrico a `rates_amount_band.py` pero sobre plazos: columnas `id`, `bank_id`, `min_days`, `max_days`.

- `get_by_bank_term(bank_id, term)`: la banda de ese banco que cubre `term` (días).
- `get_all_by_term(term)`: todas las bandas (a lo sumo una por banco) que cubren `term`, `many=True`.

Mismo patrón de consumo indirecto que `rates.py`/`rates_amount_band.py`.

#### `signatures.py` -- tabla `signatures` (el modelo más grande de `libs/orm`)

Define constantes de temporización acopladas a los workers SQS: `SIGNING_WINDOW = 15 min` (debe coincidir con el `DelaySeconds` con que se encola `check_signature_timeout` desde `create_signature`), `OTP_TTL = 2 min`, `MAX_OTP_TRIES = 3`, `SIGNING_TIMEOUT = 60 s` (coincide con el `DelaySeconds` de `check_signing_timeout`, encolado desde `resolve_otp`, como red de seguridad adicional a `SIGNING_WINDOW`).

Enum `SignatureStage`: `FORM → BIOMETRICS → SIGNATURE → OTP → SIGNING → SIGNED` (terminal) / `FAILED` (terminal). Enum `BiometricType`: `ID_FRONT, ID_BACK, FACE`, mapeado a columnas concretas vía el diccionario `BIOMETRIC_COLUMNS`.

Columnas: `id` (PK UUID), `stage`, `doc_s3_key` (único), `sign_location` (JSONB, coordenadas de estampado — ver `signature_stamp.py`), `signatory`, `email`, `id_front_s3_key`/`id_back_s3_key`/`id_face_s3_key`/`draw_s3_key`/`signed_s3_key`/`raw_signed_s3_key` (todas opcionales), `doc_hash`/`signed_hash` (SHA-256), `signed_at`, `signing_data` (JSONB, telemetría de la firma: IP, user-agent, idioma, hora de resolución del OTP), `otp_hash`, `otp_at`, `otp_tries`, `created_at`.

Métodos, todos siguiendo el patrón `update(...).returning(Signatures)`, uno por cada transición de la máquina de estados:

- `create(doc_s3_key, sign_location, signatory)` → inserta en `stage=FORM`.
- `get_by_id(signature_id)`.
- `set_email(signature_id, email)` → fija `email`, avanza a `BIOMETRICS`.
- `set_biometric_key(signature_id, biometric_type, s3_key)` → resuelve la columna vía `BIOMETRIC_COLUMNS[biometric_type]` y la actualiza (no cambia `stage`; el avance a `SIGNATURE` es un paso explícito aparte).
- `advance_to_signature_stage(signature_id)` → fija `stage=SIGNATURE`.
- `set_draw_key(signature_id, draw_s3_key)` → fija `draw_s3_key`, avanza a `OTP`.
- `set_otp(signature_id, otp_hash)` → fija `otp_hash`, `otp_at=NOW()`, resetea `otp_tries=0`.
- `register_failed_otp_attempt(signature_id)` → incrementa `otp_tries` en SQL (`Signatures.otp_tries + 1`, no en Python, para evitar carreras).
- `start_signing(signature_id, signing_data)` → fija `stage=SIGNING`, limpia `otp_hash=None` (el OTP ya se consumió) y guarda `signing_data`.
- `mark_signed(signature_id, *, signed_s3_key, raw_signed_s3_key, doc_hash, signed_hash, signed_at)` → fija `stage=SIGNED` y todos los campos terminales del documento firmado.
- `mark_failed(signature_id)` → fija `stage=FAILED`.

Usado exclusivamente por **signatures**.

#### `user_credentials.py` -- tabla `user_credentials`

PK `user_id` (UUID, 1:1 con `users`), `password_hash` (string, bcrypt), `created_at`, `updated_at`.

- `create(user_id, password_hash)`: `insert ... returning(...)`.
- `get_by_user_id(user_id)`: `select ... limit(1)`.

Usado exclusivamente por **auth** (registro/login).

#### `users.py` -- tabla `users`

Columnas: `id` (PK UUID), `email`, `full_name`, `created_at`, `updated_at`.

- `create(email, full_name)`: normaliza `email.strip().lower()` y `full_name.strip()` antes de insertar.
- `get_by_email(email)`: normaliza igual antes de buscar (`select ... limit(1)`).
- `get_by_id(user_id)`: `select ... limit(1)`.

Usado por **auth** (es su modelo principal) y, a través de `libs/utils/auth.require_auth`, leído por todos los servicios que protegen endpoints (inyecta `event["user"]`).

---

### 7.3 `libs/utils/` -- utilidades compartidas

#### `auth.py` -- emisión de tokens y el decorador `require_auth`

- `issue_token(user_id) -> tuple[str, datetime]`: genera un token aleatorio (`secrets.token_urlsafe(32)`), calcula `expires_at = now + 24h` (`TOKEN_DURATION_HOURS`), persiste `BearerTokens.create(user_id, token_hash=sha256(token), expires_at)` y devuelve `(token_en_claro, expires_at)` — el texto plano **solo** existe en esta llamada; en base de datos únicamente se guarda el hash.
- `require_auth(handler)`: decorador (`@wraps`) para handlers Lambda `(event, context)`. Algoritmo:
  1. Normaliza las cabeceras del evento a minúsculas y lee `authorization`.
  2. Si no empieza por `"bearer "` (case-insensitive) → `HandledError("missing_bearer_token", 401)`.
  3. Extrae el token (`authz[7:].strip()`); si queda vacío → `HandledError("invalid_or_expired_token", 401)`.
  4. Busca `BearerTokens.get_by_hash(sha256(token))`; si no existe, está `revoked_at is not None`, o `is_alive(bearer)` es `False` (expirado) → en los tres casos `HandledError("invalid_or_expired_token", 401)`.
  5. Resuelve `Users.get_by_id(bearer.user_id)`; si el usuario no existe → mismo error 401.
  6. Si todo pasa, inyecta `event["user"]` (instancia `Users`) y `event["token"]` (instancia `BearerTokens`) y delega al handler envuelto.

  Cada rama de fallo loguea un `WARNING` antes de lanzar. Es el decorador de autenticación que usan prácticamente todos los endpoints protegidos del repo, normalmente apilado junto con `handle_exceptions` de `libs/core/responses.py` (que es quien finalmente traduce el `HandledError` en una respuesta HTTP 401 y hace el `rollback`/`close` de la sesión).

  Usado por **auth, files, forms, processes** (y por extensión, dado que protege casi cualquier endpoint autenticado, es candidato a estar en **signatures** también, aunque el flujo de firma usa predominantemente enlaces públicos tokenizados en vez de bearer tokens de usuario).

#### `bearer_tokens.py` -- helpers de ciclo de vida del token

- `is_alive(bearer) -> bool`: `bearer.revoked_at is None and bearer.expires_at > now(UTC)`.
- `revoke(token_id) -> bool`: `BearerTokens.update_by_id(token_id, {"revoked_at": now(UTC)})`; devuelve si la actualización afectó una fila.

Usado por **auth** (logout/revocación) y por `auth.require_auth` (verificación de vigencia).

#### `biometrics.py` -- validadores de evidencia biométrica (Rekognition)

Puerto simplificado de la heurística legacy (`services/signatures/_legacy/utils/evidence.py`), ahora operando sobre una única clave S3 conocida (ya no prueba extensiones candidatas, porque el flujo nuevo sabe exactamente dónde subió el front). Límite `_MAX_EVIDENCE_BYTES = 5 MiB` (tope de Rekognition por request).

- `analyze_id_front(bucket, key) -> tuple[bool, str]`: valida tamaño (`_check_size`, que distingue `evidence_missing`/`evidence_too_large`), detecta líneas de texto con `rekognition.detect_text` filtrando por confianza ≥70 %, exige ≥3 líneas confiables y ≥6 dígitos totales detectados (umbral para asumir que hay un número de documento legible); si no, devuelve `(False, "too_few_legible_lines")` o `(False, "no_id_number_detected")`.
- `analyze_id_back(bucket, key)`: igual chequeo de tamaño, exige ≥2 líneas confiables.
- `analyze_face(bucket, key)`: usa `rekognition.detect_faces(Attributes=["EYES_OPEN"])`; rechaza si hay 0 o >1 caras, si la confianza de detección es <90 %, o si los ojos no están abiertos con confianza <80 %.

Ninguna función lanza por una foto inválida (eso es un resultado normal, `(False, reason)`); sí relanza `ClientError` de S3 que no sea 404. Usado exclusivamente por **signatures** (etapa `BIOMETRICS` del flujo de firma, endpoint `set_biometrics`).

#### `lambda_invoke.py` -- invocación Lambda-a-Lambda

Mecanismo para que un handler invoque a otro directamente vía `boto3.client("lambda").invoke`, sin pasar por API Gateway (ejemplo citado en el propio docstring: `signatures.verify_otp` disparando de forma asíncrona la Lambda interna `signatures.sign`, o invocaciones hacia los helpers de `mock_ca`). Cliente perezoso (`_get_client`, configurado con `retries={"max_attempts": 2, "mode": "standard"}`, `connect_timeout=5`, `read_timeout=30`) para no abrir sesión AWS en tests que nunca invocan de verdad; `_reset_client_for_tests()` es el hook de test para forzar su reconstrucción.

- `resolve_function_name(service, function_key, stage=None) -> str`: construye `cdts-{stage}-{service}-{function_key-con-guiones}`, exactamente la misma convención que `build-functions.js` (ver §8.1). `service=None` cae al env var `SERVICE` (el propio servicio llamante); `stage=None` cae a `STAGE`. Lanza `RuntimeError` si falta cualquiera de los dos y no fue pasado explícito — deliberado, para no arriesgarse a invocar la Lambda equivocada o en el stage equivocado por una suposición silenciosa.
- `invoke_sync(function_key, payload=None, *, service=None) -> dict`: invoca en modo `RequestResponse` (`InvocationType="RequestResponse"`), espera la respuesta, la parsea como JSON. Lanza `LambdaInvokeError` con `error_type` igual a `"boto_error"` (fallo de red/credenciales), `"bad_status"` (StatusCode ≠ 200), `"bad_payload"` (respuesta no-JSON) o `"function_error"` (la Lambda invocada terminó con excepción — AWS lo señala en `FunctionError`). Si la respuesta es un JSON no-dict, la envuelve como `{"result": parsed}`.
- `invoke_async(function_key, payload=None, *, service=None) -> None`: invoca en modo `"Event"` (fire-and-forget); sólo valida que AWS aceptó la invocación (`StatusCode == 202`, documentado así para este modo) y lanza `LambdaInvokeError("submission_failed", ...)` si no. El resultado de la Lambda invocada nunca se observa.
- `class LambdaInvokeError(Exception)`: expone `function_name`, `error_type` (uno de los cuatro tags anteriores más `"submission_failed"`) y `detail` (seguro de loguear, no pensado para mostrarse tal cual al usuario final).

Requisito de IAM explícito en el docstring: el rol de la Lambda llamante debe incluir `lambda:InvokeFunction` sobre el ARN del destino; quien conecta un nuevo flujo de invocación debe ampliar manualmente las políticas IAM en el `serverless.yml` del servicio llamante.

Usado por **processes** (dispara `signatures` de forma asíncrona al avanzar un proceso) y **signatures** (`notify_terminal_state` en `signature_notifications.py`, y potencialmente la cadena `verify_otp → sign`).

> Nota: el archivo contiene un comentario interno ("pipeline test: touching libs/ must trigger a transversal fan-out") que es simplemente texto dentro del código fuente ya existente en el repositorio — no es una instrucción operativa real ni afecta el comportamiento del módulo; se documenta aquí solo por completitud de la lectura línea por línea solicitada, no se actuó sobre él.

#### `locations.py` -- catálogos de ubicación (Colombia + países)

Carga datos estáticos desde `libs/data/locations_cities.json` y `libs/data/locations_countries.json` mediante un patrón singleton genérico (`_JsonSingletonStore`, uno por subclase gracias a `cls not in cls._instances`), de forma que el JSON se lee una sola vez por contenedor Lambda cálido.

- `class ColombianLocations`: `get_departments()`, `get_departments_map()` (con `label`), `get_department(department)`, `get_cities(department)`, `get_cities_map(department)` (con `label` y `dane_code`), `get_city(department, city)`, `get_dane_code(department, city)`. Todos son `@classmethod` que recargan los datos vía `_load_data()` (de hecho el store ya está cacheado, así que no hay I/O repetido).
- `class Countries`: `get_countries()`, `get_countries_map()` (con `label`, `abbr`), `get_country(country)`.
- `class Location`: constructor `(country, department, city)` que resuelve etiquetas legibles; si el país es Colombia, exige que tanto el departamento como la ciudad existan en el catálogo para poblar las etiquetas (si no, los campos quedan en `None`); para cualquier otro país, usa el `department`/`city` tal cual se pasaron (no hay catálogo de ciudades no colombianas). Método `full_name(include_country=True, separator=", ")`.
- `class IssuanceLocation(Location)`: variante para "lugar de expedición del documento". Si la resolución base (ciudad colombiana directa) no encontró nada y el país es Colombia, busca el nombre dado como una **localidad** (`localities`) dentro de alguna ciudad del departamento — p. ej. una localidad de Bogotá listada bajo "Bogotá D.C." en el JSON — y si la encuentra, puebla las etiquetas a partir de esa localidad padre.

Usado exclusivamente por **forms** (formulario KYC: nacionalidad, lugar de nacimiento, lugar de expedición del documento).

#### `otp_email.py` -- plantilla del correo de verificación OTP

Puerto de `services/signatures/_legacy/utils/otp_email.py`, adaptado al esquema simplificado de la v2 (usa `signature_id` en vez de `sign_id`, y los campos `signatory`/`email` en vez de columnas `signer_name`/`signer_email` separadas). Deliberadamente el correo no incluye un enlace para firmar: el firmante ya tiene esa URL abierta, es como llegó hasta ahí.

- `render_otp_email(*, otp, signatory, issued_at, ttl, signature_id) -> tuple[str, str]`: devuelve `(subject, html_body)`. El HTML es una plantilla fija con el código centrado, la hora de expiración calculada (`issued_at + ttl`) y los primeros 8 caracteres del `signature_id` como referencia visible al pie.

Usado por **signatures** (`set_otp`), vía `libs/core/mailer.send_email`.

#### `passwords.py` -- hashing de contraseñas (bcrypt)

Vive deliberadamente separado de `auth.py`: bcrypt trae una extensión nativa compilada, así que cualquier servicio que lo importe debe compilar su wheel para la plataforma Lambda (Linux); mantener bcrypt fuera de `auth.py` permite que el resto de servicios que sólo necesitan `require_auth` sigan con dependencias puro-Python.

- `hash_password(plain: str) -> str`: `bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12))`.
- `verify_password(plain: str, hashed: str) -> bool`: `bcrypt.checkpw`, atrapa `ValueError`/`TypeError` (hash corrupto o de formato distinto) devolviendo `False` en vez de propagar.

Usado exclusivamente por **auth**.

#### `rates.py` -- ranking de tasas y cálculo de rendimiento

- `get_ranked_rates(amount: Decimal, term: int) -> list[tuple[int, Decimal]]`: resuelve, para cada banco, su banda de monto (`AmountBand.get_all_by_amount`) y su banda de plazo (`TermBand.get_all_by_term`); interseca los bancos que tienen ambas bandas (`.keys() & .keys()`), construye los pares `(amount_band_id, term_band_id)` y delega en `Rate.get_all_by_bands(band_pairs)`, que devuelve `[(bank_id, rate), ...]` con la mejor tasa primero.
- `yield_cop(amount: Decimal, ea_pct: Decimal, days: int) -> tuple[Decimal, Decimal]`: rendimiento compuesto sobre base de 365 días a partir de una tasa efectiva anual (`ea_pct`), devuelve `(interés, monto_final)` redondeados a centavo (`quantize(Decimal("0.01"))`).

Usado exclusivamente por **banks** (simulador de tasas).

#### `validators.py` -- validaciones genéricas de entrada

- `valid_email(value) -> bool`: regex simple `^[^@\s]+@[^@\s]+\.[^@\s]+$`, además de tipo `str` y longitud ≤320.
- `password_reason(value) -> str | None`: devuelve el código de error (`"password_required"`, `"password_too_short"` si <10 caracteres, `"password_needs_letter"`, `"password_needs_digit"`) o `None` si la contraseña es válida.

Usado por **auth** (registro) y **signatures** (probablemente en validación de email del firmante).

#### `signature_audit_page.py` -- página de evidencia PDF

Construye con `reportlab` la página final que se añade a todo PDF firmado: datos del firmante, fecha/hora, una grilla 2×2 con las fotos de documento de identidad (frente/reverso), la selfie y la firma dibujada, más una sección de "datos técnicos" (serial del certificado, hash del documento, IP, user-agent, idioma del navegador, y el momento de validación del OTP si está presente en `signing_data`). Usa tipografía IBM Plex empaquetada como TTF (reportlab no puede incrustar OTF con sabor CFF) y debe ejecutarse **antes** de aplicar la firma PAdES, porque PAdES sólo cubre los bytes existentes al momento de firmar — añadir algo después haría que el documento se lea como manipulado.

Único punto de entrada público: `build_audit_page(*, signature_id, signatory, email, id_front_png, id_back_png, face_png, draw_png, signed_at, cert_serial, document_hash, signing_data) -> bytes`, que devuelve un PDF de una sola página (tamaño Letter). El resto del módulo son helpers privados de layout (`_eyebrow`, `_section_title`, `_draw_cell`, `_status_pill`, `_data_row`, etc.) sin interfaz pública propia. Nota de implementación: `document_hash` corresponde al hash del PDF *antes* de anexar esta página (el `raw_signed`, no el `signed` final, que todavía no existe en ese punto).

Usado exclusivamente por **signatures** (`sign_doc`).

#### `signature_ca.py` -- Autoridad Certificadora simulada (Mock CA)

Puerto recortado de `services/signatures/_legacy/utils/mock_ca.py`: sólo conserva las dos operaciones que necesita `sign_doc` (emitir un certificado transaccional y firmar un PDF en PAdES); no se portó `verify_pades_pdf` porque esta refactorización todavía no tiene un endpoint `/verify`.

Modelo de confianza (simulado, mismo esquema raíz que el servicio legacy): el certificado y la llave privada raíz viven en SSM como `SecureString` bajo `/cdts/{stage}/mock-ca/root/cert-pem` y `/cdts/{stage}/mock-ca/root/private-key-pem` (cifrados con KMS), se cargan una sola vez por contenedor cálido (`_load_root_ca`, cacheado en `_root_ca_cache`) y **sólo** se usan para certificar un certificado hoja efímero por firma (nunca firman el documento directamente). Esa llave hoja (RSA-2048, 1 hora de validez) vive únicamente en la memoria de la Lambda invocadora durante la llamada y nunca se persiste.

- `issue_transaction_cert(signature_id, signer_email, signer_name=None, valid_hours=1) -> tuple[bytes, bytes, str]`: genera el par de llaves RSA-2048, construye un certificado X.509 (asunto con `CN`, `emailAddress`, `OU=signature_id`; extensiones `BasicConstraints(ca=False)`, `KeyUsage(digital_signature, content_commitment)`, `SubjectAlternativeName` con el email) firmado por la CA raíz con SHA-256, y devuelve `(cert_pem, private_key_pem, serial_hex)`. El serial es aleatorio (16 bytes de `secrets.token_bytes`, 128 bits de entropía), no secuencial.
- `sign_pdf_pades_b(pdf_bytes, cert_pem, private_key_pem, *, reason=..., location=None) -> bytes`: usando `pyhanko`, agrega un campo de firma invisible (`SigFieldSpec`, `SIG_FIELD_NAME = "CDTsSignature1"`) y aplica una firma PAdES-B baseline. El widget es invisible a propósito: el trazo visual de la firma ya fue estampado antes por `signature_stamp.py`; PAdES-B es válido sin widget visible y los lectores igual muestran el panel de firmas.

Usado exclusivamente por **signatures** (`sign_doc`).

#### `signature_notifications.py` -- disparo centralizado de notificaciones post-firma

Centraliza las notificaciones desde los **cuatro** puntos del código que pueden fijar un estado terminal de una firma (`SIGNED` o `FAILED`): `sign_doc` (SIGNED), y `resolve_otp` / `check_signature_timeout` / `check_signing_timeout` (FAILED) — para que esos cuatro sitios no se desincronicen entre sí sobre qué notificar.

- `notify_terminal_state(signature_id, stage: str, *, notify_signer: bool = False) -> None`: siempre invoca de forma asíncrona (`invoke_async`) la función `"sign_trigger"` con `{signature_id, stage}` (dispara para ambos estados terminales); si `notify_signer=True` (sólo tiene sentido en `SIGNED`), además invoca `"notify_signed"` con `{signature_id}` (el correo de "firmaste un documento"). Ambas invocaciones son best-effort: si el *envío* de la invocación falla (`LambdaInvokeError`), se loguea como `ERROR` pero nunca se relanza — la transición de estado de la firma, que ya ocurrió, no debe revertirse por un problema de la plomería de notificaciones. El resultado de la Lambda invocada (su propio best-effort interno) no se observa aquí.

Usado exclusivamente por **signatures**.

#### `signature_stamp.py` -- estampado de la firma dibujada sobre el PDF

Puerto de `services/signatures/_legacy/utils/stamp.py`; el formato de coordenadas (`sign_location`) es exactamente el que ya usa la columna `Signatures.sign_location`: `{"page": int (1-indexado), "x_pct", "y_pct"}` (porcentajes desde la esquina superior izquierda, convención amigable para UI) más opcionalmente `"width_pct"` (default 25.0) y `"height_pct"` (si se omite, se deriva del aspect ratio propio del PNG dibujado).

- `stamp_drawing_on_pdf(pdf_bytes: bytes, drawing_png: bytes, sign_location: dict) -> bytes`: valida que la página exista, convierte el porcentaje `y_pct` (desde arriba, convención UI) a coordenadas PDF (origen abajo-izquierda), dibuja la imagen con `reportlab` sobre un canvas temporal del mismo tamaño que la página, y la fusiona (`page.merge_page`) sólo en la página objetivo usando `pypdf`. **No es idempotente**: llamarla dos veces estampa dos veces. El PDF resultante es el que luego firma `signature_ca.sign_pdf_pades_b` — es decir, cualquier manipulación posterior del trazo rompería el hash cubierto por PAdES.

Usado exclusivamente por **signatures** (`sign_doc`).

#### `signed_email.py` -- plantilla del correo "firmaste un documento"

Se envía una sola vez por firma, justo después de que `sign_doc` marca la firma como `SIGNED`. Enlaza al PDF firmado completo (con la página de evidencia) en vez de adjuntarlo: `mailer.send_email` no soporta adjuntos, y un enlace presignado mantiene el correo liviano sin importar el tamaño del archivo.

- `render_signed_email(*, signatory, signed_at, signed_url, signature_id) -> tuple[str, str]`: devuelve `(subject, html_body)`; el HTML incluye un botón de descarga apuntando a `signed_url` y una nota de que el enlace expira pronto.

Usado por **signatures**, vía `libs/core/mailer.send_email`.

---

## 8. Mecanismo de build y despliegue

### 8.1 Convención de auto-registro de handlers (`backend/utils/build-functions.js`)

Este módulo Node implementa la convención que evita declarar manualmente, bloque por bloque, cada función en `serverless.yml`. Cada bloque desplegable (`services/<svc>/` o `platform/<block>/`) conecta su propio `functions.js`:

```js
// backend/<services|platform>/<block>/functions.js
module.exports.build = require('../../utils/build-functions')(__dirname);
```

y lo referencia desde `serverless.yml` con `functions: ${file(./functions.js):build}`. `build-functions.js` exporta una *factory* `(serviceDir) => async ({ options, resolveConfigurationProperty }) => {...}` — la firma exacta que Serverless Framework v3 espera de una variable dinámica resuelta vía `${file(...)}`: recibe `options` (incluye `stage`/`s` de la CLI) y `resolveConfigurationProperty` (para leer el `service:` ya resuelto del propio `serverless.yml`).

Algoritmo, por cada tipo de carpeta en `TYPES = ['handlers', 'scheduled', 'workers']` bajo `src/`:

1. Si `src/<type>/` no existe, la salta.
2. Lista cada subcarpeta (orden alfabético, `fs.readdirSync(...).sort()`); ignora lo que no sea directorio.
3. Exige que exista `function.yml` dentro de esa carpeta — si falta, lanza un error explícito (`Missing function.yml in <ruta>`), deteniendo el build. Esto obliga a que **todo** handler tenga su propio archivo de configuración, aunque esté vacío.
4. Valida que el nombre de la carpeta sea snake_case (`^[a-z][a-z0-9_]*$`) — si no, lanza error (`must be snake_case`); la razón dada en el propio código es que Python no puede importar paquetes con guiones.
5. Carga el `function.yml` (vía `js-yaml`) en un objeto `custom`.
6. Deriva `folderKebab = folder.replace(/_/g, '-')` (snake_case → kebab-case) y construye la entrada final:

```js
functions[folder] = {
  name: `cdts-${stage}-${service}-${folderKebab}`,
  handler: `src/${type}/${folder}/handler.handler`,
  ...custom,  // spread al final: cualquier clave de function.yml PISA la derivada
};
```

Es decir, `name` y `handler` siempre se calculan primero por convención, pero el spread `...custom` se aplica *después*, de modo que si `function.yml` define explícitamente `name:` o `handler:`, esos valores ganan (escape hatch documentado tanto en el header del archivo como en el test). Cualquier otra clave arbitraria de Serverless (`events`, `memorySize`, `timeout`, `environment`, `layers`, `description`, etc.) simplemente se copia tal cual al objeto de la función — `build-functions.js` no la interpreta, sólo la transporta.

`stage` se resuelve de `options.stage || options.s || 'dev'` (default `dev` si no se pasa `--stage`/`-s`), y `service` viene siempre de `resolveConfigurationProperty(['service'])` (el nombre declarado en el `service:` del propio `serverless.yml` del bloque).

El archivo de test `backend/tests/build-functions.test.js` (ejecutado con `node --test` en el job `Validate` de CI, ver §8.4) cubre, entre otros casos reales:

- Derivación automática de `name`/`handler` a partir de carpeta + servicio + stage (`src/handlers/refresh_token/` con `service=auth, stage=dev` → `name: cdts-dev-auth-refresh-token`, `handler: src/handlers/refresh_token/handler.handler`).
- Kebab-case correcto para carpetas multi-palabra (`create_signature` → `...-create-signature`).
- Que `scheduled` y `workers` se escanean igual que `handlers`.
- Override explícito de `name` y de `handler` vía `function.yml` (el "escape hatch").
- Preservación de campos arbitrarios (`events`, `memorySize`, `environment`, `layers`, `description`, ...).
- `function.yml` vacío sigue produciendo `name`/`handler` válidos.
- `function.yml` ausente lanza el error esperado (`Missing function.yml in src[\\/]handlers[\\/]oops`).
- Carpeta en kebab-case o con mayúsculas se rechaza (`must be snake_case`).
- Un servicio sin `src/` devuelve un mapa de funciones vacío (`{}`), sin error.
- El stage por defecto es `dev` cuando no se pasa `options.stage`.

Un ejemplo real de `function.yml` consumido por este mecanismo es `backend/services/auth/src/handlers/login/function.yml` (y análogos en `logout/`, `me/`, etc.), donde cada handler define sus propios `events`/`timeout`/`memorySize` sin tocar jamás el `serverless.yml` del bloque.

### 8.2 Composición multi-servicio (`backend/serverless-compose.yml`)

Serverless Framework v3 permite orquestar múltiples stacks (uno por "servicio" en su terminología) desde un único archivo raíz `serverless-compose.yml`, resolviendo el orden de despliegue por dependencias declaradas. En este repo compone 7 bloques:

| Servicio | Ruta | `dependsOn` |
|---|---|---|
| `migrations` | `platform/migrations` | — |
| `assets` | `platform/assets` | — |
| `auth` | `services/auth` | `migrations` |
| `banks` | `services/banks` | `migrations` |
| `files` | `services/files` | `migrations` |
| `forms` | `services/forms` | `migrations` |
| `processes` | `services/processes` | `migrations` |
| `signatures` | `services/signatures` | `migrations`, `files` |

Lectura del grafo: `migrations` y `assets` son bloques de plataforma (no de negocio) sin dependencias propias — `migrations` aplica el esquema SQL, `assets` sincroniza archivos estáticos a S3 (ambos corren en el job `infrastructure` de CI, ver §8.4). Los cinco servicios de negocio (`auth`, `banks`, `files`, `forms`, `processes`) dependen únicamente de `migrations` (necesitan el esquema de base de datos ya aplicado antes de desplegar). `signatures` es el único con una dependencia cruzada *de servicio a servicio*: además de `migrations`, depende de `files` — consistente con que `signatures` reutiliza infraestructura/convenciones de `files` para el manejo de documentos (y, a nivel de código, con que `processes` invoca a `signatures` vía `lambda_invoke` para firmar documentos que `files` registró).

Este `serverless-compose.yml` leído en este worktree **no contiene referencias cross-stack explícitas con la sintaxis `${cf:<stack>.<Output>}`** — ese mecanismo (consultar un `Output` de CloudFormation de otro stack ya desplegado, típicamente para pasar un ARN de bucket, un ID de VPC, o el nombre de una Layer) es parte del mecanismo general de Serverless Framework y sí se usa dentro de cada `serverless.yml` de bloque individual para leer outputs de otros stacks (por ejemplo, un `function.yml` referenciando la Layer de otro bloque, ver §8.5), pero no aparece en el archivo de composición raíz mismo.

### 8.3 Convención de testing (`backend/conftest.py`)

Este `conftest.py` es el bootstrap de pytest para **todo** el monorepo backend (se carga una sola vez, antes de recolectar cualquier módulo de test, incluidos los `test.py` colocados junto a cada `handler.py`). Su contrato, explícito en el docstring del propio archivo, es mantenerse "lean y side-effect-only-at-import", porque es el único lugar donde se neutralizan las llamadas AWS/drivers nativos que `libs/core/db.py` dispara al importarse.

Cuatro responsabilidades, en orden:

1. **Flag `--integration`** (`pytest_addoption` + `pytest_collection_modifyitems`): registra la opción de CLI `--integration`. Sin ella, cualquier test marcado `@pytest.mark.integration` se recolecta pero se **salta automáticamente** (vía `pytest.mark.skip`), de modo que un `pytest` normal (local o el job `test` de CI) nunca toca infraestructura real. El job `integration` de CI (ver §8.4) es el único que pasa `--integration`.

2. **`sys.path`**: inserta la raíz `backend/` al principio de `sys.path`, para que los tests puedan hacer `from libs.core... import ...` exactamente igual que en runtime (donde el `cwd` de Lambda es la raíz del ZIP empaquetado, que refleja `backend/`).

3. **Variables de entorno default** (sólo si no se está corriendo `--integration`, detectado mirando `sys.argv` directamente — para no alterar nada cuando el run es de integración contra infraestructura real `dev`): `STAGE=test`, `SSM_DB_PATH=/cdts/test/db`, `FILES_BUCKET=cdts-test-files`, `ASSETS_BASE_URL=https://assets.test`, más variables específicas de `signatures` (`SIGNATURES_BUCKET`, `SIGNATURE_TIMEOUT_QUEUE_URL`, `SIGNING_TIMEOUT_QUEUE_URL`, `SSM_FRONTEND_PATH`, `SSM_SIGNATURES_SERVICE_KEY`, `SSM_SMTP_PATH`), todas con `setdefault` (no sobreescriben si CI ya las fijó).

4. **Stub de `boto3`** (también sólo fuera de `--integration`): antes de que cualquier handler pueda importar `libs.core.db`, sustituye el módulo `boto3` completo en `sys.modules` por un módulo falso cuyo `.client(...)`/`.resource(...)` devuelven siempre una instancia de `_FakeAWSClient`. Esa clase responde de forma realista sólo a `get_parameters_by_path` (devuelve 5 parámetros falsos — `host, port, name, user, password` — bajo el `Path` pedido, para que `_load_db_config()` arme una URL de conexión sintácticamente válida) y a `get_parameter` (devuelve un valor vacío); cualquier otro método (Rekognition, S3, SES, SQS, Lambda...) cae en `__getattr__` y devuelve un `MagicMock()` genérico. Como el engine de SQLAlchemy es perezoso, nunca se abre una conexión real. El docstring advierte explícitamente por qué este stub **no** debe instalarse en modo `--integration`: llamadas reales como `boto3.client("cloudformation").describe_stacks(...)` recibirían un `MagicMock` (que es "truthy"), lo que podría romper silenciosamente control de flujo (p. ej. paginadores que nunca terminan).

5. **Fixture `load_handler`**: devuelve la función `_load_sibling_handler(test_file)`, que:
   - Resuelve `handler.py` en el mismo directorio que el `test.py` que la invoca (si no existe, falla con un mensaje claro: "Lambda tests must be colocated with their handler").
   - Cachea el módulo cargado por ruta (`_handler_cache`) para no reimportar en cada test de un mismo archivo.
   - Encuentra la raíz del "bloque" (`_find_block_root`: sube directorios hasta encontrar uno con `serverless.yml`) y la antepone a `sys.path`, purgando y re-vinculando de forma sintética los paquetes de namespace locales `utils`/`data` (`_purge_block_local_modules` + `_bind_block_local_packages`) — esto es necesario porque cada bloque de servicio tiene su propia carpeta local `utils/`/`data/` empaquetada junto al handler en el ZIP, y Python cachea el `__path__` de un paquete de namespace la primera vez que se importa; sin esta purga/rebind, el primer bloque de test que se ejecute "ganaría" esas carpetas para toda la sesión de pytest, haciendo que los tests de otros servicios importen el `utils/` equivocado.
   - Importa el `handler.py` bajo un nombre de módulo único derivado de los últimos 3 segmentos de su ruta (p. ej. `cdts_h_handlers_login` o `cdts_h_workers_on_upload`), evitando colisiones en `sys.modules` entre handlers que todos se llaman literalmente `handler.py`.

   Uso típico dentro de un `test.py` colocado: `h = load_handler(__file__)`, luego `monkeypatch.setattr(h, "Users", MagicMock(...))` para interceptar el ORM, y finalmente `h.handler({"body": "..."}, None)`.

**`test.py` vs `integration.py`**: ambos viven colocados junto a cada `handler.py` (`src/<type>/<folder>/`). `test.py` son pruebas unitarias puras — corren siempre, sin red, con el ORM/boto3 stubbeado, usando `load_handler` + `monkeypatch`; es lo que ejecuta el job `test` de `service-package.yml` (`python -m pytest services/<svc> ...`, sin `--integration`). `integration.py` son pruebas opcionales que golpean infraestructura real ya desplegada en `dev` (API Gateway, Postgres, S3) y están marcadas `@pytest.mark.integration`; sólo corren cuando CI invoca `pytest --integration -m integration` (job `integration`, exclusivamente en `dev`, nunca en `pro`, y configurado como `continue-on-error: true` — su fallo nunca revierte un deploy que ya tuvo éxito).

### 8.4 CI/CD (GitHub Actions)

En este worktree, `.github/workflows/` contiene **4** archivos (a diferencia de los 6 mencionados en el enunciado original de esta tarea — `check-debug-otp-dev.yml` y `export-debug-otp-dev.yml` no existen en esta copia de solo lectura; probablemente viven en otra rama no incluida aquí, junto con la Lambda Layer de Tesseract mencionada en §8.5). Los 4 presentes:

#### `deploy-dev.yml`

- **Trigger**: `push` a la rama `develop`, o manual (`workflow_dispatch`) con un input opcional `block` (vacío = auto-detectar; `__all__` = forzar deploy completo; o el nombre de un servicio/bloque de infraestructura puntual).
- **Flujo** (grupo de concurrencia `deploy-dev`, sin cancelar ejecuciones en curso):
  1. **`plan`**: hace checkout completo (`fetch-depth: 0`), busca el SHA del último run *exitoso* de este mismo workflow en esta rama (vía `gh run list --status=success`, para anclar el diff incluso si un pipeline previo falló a mitad de camino) y corre `scripts/ci/plan-deploy.sh`, que calcula qué cambió desde ese SHA y produce los outputs `services_to_deploy` (lista JSON), `run_migrations`, `run_assets`, `run_infrastructure`, `transversal` (un cambio "transversal" — fuera de `backend/services/<X>/`, p. ej. tocar `backend/libs/` — fuerza que `services_to_deploy` incluya **todos** los servicios) y los contadores `services_count`/`total_count`.
  2. **`validate`** (si `total_count != 0`): instala Node + Python, corre `scripts/ci/lint-migrations.py`, los tests JS con `node --test tests/*.test.js` (incluye `build-functions.test.js`) y el pytest "cross-cutting" de `backend/tests/` (no confundir con los tests colocados por servicio).
  3. **`infrastructure`** (sólo si `run_infrastructure == true` y `validate` tuvo éxito; ambiente GitHub `dev`): configura credenciales AWS y, condicionalmente según los flags del plan, hace `serverless-compose "migrations:deploy"` seguido de invocar la Lambda `cdts-dev-migrations-apply` (aplicando el esquema SQL y fallando el job si la respuesta contiene `"errorType"`), y/o `serverless-compose "assets:deploy"` seguido de `scripts/ci/deploy-assets.sh` (sincroniza archivos a S3). Siempre vuelca un JSON de estado como artifact (`infrastructure-status`), incluso si algún paso falló (`if: always()`).
  4. **`services`** (matriz, una celda por cada servicio en `services_to_deploy`, `fail-fast: false`): invoca el workflow reusable `service-package.yml` por cada servicio en paralelo, pasando `stage: dev`.
  5. **`summary`** (`if: always()`): descarga todos los artifacts `*-status*` y renderiza una tabla Markdown en `$GITHUB_STEP_SUMMARY` con el resultado de cada etapa de infraestructura y, por servicio, de `validate/test/deploy/integration` y en qué etapa se detuvo si falló.
- **Rama/ambiente afectado**: `develop` → ambiente `dev`.

#### `deploy-pro.yml`

Estructura idéntica a `deploy-dev.yml` (mismo pipeline `plan → validate → infrastructure → services → summary`), con las diferencias explícitas documentadas en el propio archivo: dispara en `push` a `main` (grupo de concurrencia `deploy-pro`), usa el ambiente GitHub `pro`, invoca `serverless-compose ... --stage pro` y `cdts-pro-migrations-apply`, y pasa `stage: pro` al workflow reusable — lo cual, dentro de `service-package.yml`, **desactiva** el job `integration` (condicionado a `inputs.stage == 'dev'`) porque, según el comentario del propio pipeline, no hay usuarios de prueba en la base de datos de producción. La tabla de resumen tampoco incluye la columna "Integration".
- **Rama/ambiente afectado**: `main` → ambiente `pro` (producción).

#### `service-package.yml` (workflow reusable, `workflow_call`)

No se dispara directamente por push/PR/manual; es invocado por `deploy-dev.yml`/`deploy-pro.yml` una vez por cada servicio en la matriz, recibiendo `service` (nombre de carpeta bajo `backend/services/`) y `stage` (`dev`/`pro`) como inputs. Implementa el pipeline por servicio en 5 jobs encadenados:

1. **`validate`**: dry-run de empaquetado (`serverless-compose "<svc>:package" --stage <stage>`) tras verificar que el servicio está registrado en `serverless-compose.yml`; detecta errores de YAML, handlers faltantes o salidas mal formadas de `build-functions.js` en ~30-45s, sin gastar tiempo en tests si la config ya está rota.
2. **`test`** (si `validate` tuvo éxito): corre los `test.py` colocados de ese servicio (`python -m pytest services/<svc>`, con `STAGE=test` fijo — nunca el stage real, porque las pruebas unitarias no deben tocar infraestructura real); si no encuentra ningún `test.py` bajo el servicio, emite un `::warning::` pero no falla el job.
3. **`deploy`** (si `validate` y `test` tuvieron éxito; ambiente GitHub `<stage>`): configura credenciales AWS, verifica identidad (`aws sts get-caller-identity`) y corre `serverless-compose "<svc>:deploy" --stage <stage>`.
4. **`integration`** (sólo si `stage == 'dev'` y `deploy` tuvo éxito; `continue-on-error: true`): detecta `integration.py` colocados; si hay alguno, corre `pytest --integration -m integration` contra la infraestructura real recién desplegada en `dev` (con `AWS_EC2_METADATA_DISABLED=true` porque los runners de GitHub no son instancias EC2 y de otro modo el SDK de AWS intenta sondear IMDS y se cuelga). Su fallo nunca bloquea el pipeline (de ahí `continue-on-error`), ya que el deploy ya ocurrió exitosamente.
5. **`record_status`** (siempre corre, `if: always()`): junta los resultados de las 4 etapas anteriores en un único JSON (`service-status-<service>`) que `deploy-dev.yml`/`deploy-pro.yml` descargan en su job `summary` para construir la tabla final.

#### `remove-service.yml`

- **Trigger**: exclusivamente manual (`workflow_dispatch`), con inputs `service` (carpeta bajo `backend/services/`), `stage` (`dev`/`pro`, por defecto `dev`) y `empty_buckets` (booleano, default `false`).
- **Propósito**: escape hatch manual para hacer `sls remove` de un stack individual cuando CloudFormation queda en un estado irrecuperable (nombres de ruta paramétrica desalineados, IDs lógicos de Cognito User Pool desalineados, buckets S3 huérfanos, etc.) y ya no puede "roll-forward" con un deploy normal. El propio comentario del archivo advierte explícitamente: nunca ejecutarlo contra `pro` sin confirmación explícita (está protegido por el *environment gate* de GitHub sobre `inputs.stage`).
- **Flujo**: imprime una advertencia si el stage es `pro`; si `empty_buckets=true`, lista los buckets S3 propiedad del stack (`ResourceType == AWS::S3::Bucket` en `cloudformation list-stack-resources`) y los vacía por completo (objetos, versiones y delete-markers) antes de intentar el remove, porque CloudFormation se niega a borrar un bucket no vacío; finalmente ejecuta `serverless-compose "<service>:remove" --stage <stage>`. El comentario del archivo aclara que el workflow **no** toca infraestructura compartida (RDS, parámetros SSM, Cognito) — eso se borra a mano si corresponde.
- **Rama/ambiente afectado**: ninguno fijo — actúa sobre el stack `cdts-<stage>-<service>` que el operador indique al disparar el workflow manualmente.

### 8.5 Mecanismo de Lambda Layers

Una **Lambda Layer** en Serverless Framework v3 es un paquete de dependencias (código, binarios, librerías nativas) que se declara aparte del código de la función, bajo la clave de nivel superior `layers:` en `serverless.yml`:

```yaml
layers:
  miLayer:
    path: layer                     # carpeta que se empaqueta como .zip
    compatibleRuntimes:
      - python3.12
```

Al desplegar, Serverless crea un recurso CloudFormation `AWS::Lambda::LayerVersion` cuyo **logical ID** sigue la convención `<NombrePascalCase>LambdaLayer` (p. ej. la clave `miLayer` genera el logical ID `MiLayerLambdaLayer`), y expone su ARN como un `Output` del stack con ese mismo nombre. Una función de **otro** bloque (u otro stack) puede referenciar esa Layer ya desplegada leyendo ese output cross-stack desde su propio `function.yml`:

```yaml
layers:
  - ${cf:cdts-${sls:stage}-<bloque-que-publica-la-layer>.MiLayerLambdaLayer}
```

(la sintaxis `${cf:<stack>.<Output>}` es el mecanismo general de Serverless Framework para leer un `Output` de CloudFormation de un stack ya desplegado — el mismo tipo de referencia mencionado en §8.2 para composición entre servicios).

En tiempo de ejecución, AWS Lambda monta el contenido de cada Layer asociada a la función en el directorio `/opt` del contenedor de ejecución (en el orden declarado, si hay varias), y automáticamente antepone `/opt/bin` a la variable de entorno `PATH` y `/opt/lib` a `LD_LIBRARY_PATH` — por lo que cualquier binario o librería compartida (`.so`) empaquetado en esas subcarpetas queda disponible para el código de la función sin configuración adicional. Esto es lo que permite, por ejemplo, empaquetar un binario pesado (como un motor de OCR) una sola vez como Layer y reutilizarlo desde varias funciones sin inflar el paquete de despliegue de cada una.

El único caso real de esta mecánica en el monorepo — la Layer de Tesseract OCR usada por el servicio `documents` — no está presente en este worktree (vive en otra rama) y se documenta aparte en la sección correspondiente a ese servicio.

---

## 9. Servicio `documents` (C11 — pendiente de merge a `develop`)

> **Nota de estado:** a diferencia de los 6 servicios anteriores, `documents`
> todavía NO está mergeado a `develop` — vive en la rama
> `feat/documents-c11-basic-flow`, verificada exhaustivamente (suite unitaria
> completa + test-merge limpio contra el `develop` actual + smoke test local
> del OCR real contra la imagen base de Lambda) pero pendiente de que se abra
> y mergee su Pull Request. Esta sección documenta ese código tal como existe
> en esa rama hoy.

### 9.1 Propósito

Implementa el caso de uso C11 ("Capturar y validar documentación de soporte"):
el inversionista sube una foto de su cédula (`id_front`) durante el wizard de
apertura de un CDT, y el backend la valida de forma automática — sin
intervención humana — antes de dejar avanzar el proceso. La validación cubre
tres preguntas, en este orden: ¿el archivo es realmente lo que dice ser
(formato/tamaño)?, ¿se puede leer texto en él con suficiente confianza
(legibilidad)?, y ¿el nombre que aparece coincide con el que el inversionista
declaró en el formulario (correspondencia)? Cubre también dos flujos
alternos del catálogo C11: FA1 (reutilizar un documento ya validado de un
proceso anterior, si sigue vigente) y FE1 (rechazar con un motivo explícito
cuando el formato no es válido o el documento es ilegible).

### 9.2 Arquitectura de despliegue

**`serverless.yml`:**
- `provider`: runtime `python3.12`, `memorySize: 1024`, `timeout: 30`,
  `logRetentionInDays: 14`, `stackName: cdts-${sls:stage}-documents`.
- `httpApi.cors: true` (sin restricción de headers, a diferencia de
  `signatures`).
- `environment`: `STAGE`, `SSM_DB_PATH` (credenciales de Postgres vía SSM,
  mismo patrón que todos los servicios) y `DOCUMENTS_BUCKET`
  (`cdts-${sls:stage}-documents`).
- `iam.role.statements`: `ssm:GetParametersByPath` sobre el path de DB, y
  `s3:GetObject`/`s3:PutObject` sobre el bucket propio del servicio — sin
  `s3:ListBucket` (a diferencia de `signatures`), porque `documents` nunca
  necesita hacer HeadObject-probing de claves que podrían no existir.
- `plugins`/`custom`: `serverless-python-requirements` con
  `dockerizePip: false` — el único paquete no-PyPI que necesita (el binario
  `tesseract`) NO se empaqueta por este plugin, sino vía Lambda Layer (ver
  9.4).
- `package.patterns`: empaqueta `src/**`, `domain/**` y `libs/**`; excluye
  `test.py`/`integration.py`/`conftest.py` del zip final.
- `resources.Resources.DocumentsBucket`: bucket S3 con
  `BlockPublicAcls`/`BucketOwnerEnforced`/`SSEAlgorithm: AES256`, CORS para
  `PUT`/`GET`/`HEAD` desde cualquier origen (necesario para que el navegador
  suba directo con la URL prefirmada), y **dos zonas de retención** distintas
  en el mismo bucket (mismo patrón que `signatures`):
  - `transactions/` (dato crudo tal como se subió): expira a los 30 días —
    minimización de datos personales sensibles.
  - `evidencia-validada/` (solo lo que terminó `validado`): pasa a
    `GLACIER_IR` a los 30 días y expira a los 3650 días (10 años) — evidencia
    regulatoria de largo plazo, con lectura en milisegundos aun archivada.
  - `NotificationConfiguration.LambdaConfigurations`: dispara el worker
    `on_upload` ante `s3:ObjectCreated:*` filtrado por prefijo `transactions/`
    — este bloque de permisos (`AWS::Lambda::Permission`) es manual porque
    Serverless Framework v3 no genera automáticamente el permiso de invocación
    cuando el trigger S3 se declara a mano en `resources` en vez de en
    `events:` de la función.
- `Outputs.DocumentsBucketName`: expone el nombre del bucket para que otros
  stacks (o scripts de bootstrap) puedan referenciarlo.

**`requirements.txt`:**
| Librería | Versión | Para qué |
|---|---|---|
| `sqlalchemy` | 2.0.34 | ORM (`libs.orm.documents`) |
| `pg8000` | 1.31.2 | Driver Postgres puro-Python (sin dependencias nativas de compilación, apto para el zip de Lambda) |
| `scramp` | 1.4.17 | SCRAM-SHA-256 auth — `pg8000` 1.31.x dejó de empaquetarlo internamente; sin este pin explícito, la conexión a Postgres falla en runtime |
| `pytesseract` | 0.3.13 | Wrapper Python sobre el binario `tesseract` (NO lo reemplaza — necesita el binario real instalado, ver 9.4) |
| `Pillow` | 10.4.0 | Decodifica los bytes de la imagen (`Image.open`) antes de pasarla a `pytesseract` |
| `rapidfuzz` | 3.14.6 | Fuzzy matching (`fuzz.token_sort_ratio`) tolerante a ruido de OCR al comparar el nombre extraído contra el declarado |

**Auto-registro de handlers:** igual mecanismo que el resto del backend —
`functions.js` llama a `backend/utils/build-functions.js` (documentado en
detalle en la sección 8.1), que escanea `src/handlers/*` y `src/workers/*`.

### 9.3 Handlers

#### `upload_url` — `POST /upload-url` (por defecto, sin `function.yml`)
- `handler(event, context)`, decorado con `@handle_exceptions` y
  `@require_auth`.
- Lee `process_id`, `document_type`, `content_type` del body JSON.
- Valida: `process_id` presente, `document_type ∈ {"id_front"}` (slice
  básico — FA2 extiende este set en un slice futuro, deliberadamente no
  adelantado).
- Construye la key `transactions/{process_id}/{document_type}/{uuid4()}.{ext}`
  (extensión inferida del `content_type` vía `_EXT_BY_CONTENT_TYPE`).
- Llama a `libs.core.s3.presign_upload(bucket, key, content_type)` y devuelve
  `{upload_url, key, content_type}`.
- **No escribe nada en la base de datos** — la fila `Documentos` la crea el
  worker `on_upload` solo cuando S3 confirma que el archivo llegó (mismo
  límite de diseño que `files/get_upload_url`). Esto es intencional: responde
  en milisegundos (Q04R01, no bloquear la interfaz) y delega todo el trabajo
  pesado al pipeline asíncrono.

#### `check_reuse` — `GET /check-reuse` (por defecto)
- `@handle_exceptions` + `@require_auth`. Lee `document_type` y `process_id`
  de `queryStringParameters`.
- Verifica que el proceso exista y pertenezca al usuario autenticado
  (`Processes.get_by_id` + comparación de `user_id`) — dueño incorrecto
  responde `404 process_not_found`, no `403`, para no revelar si el proceso
  existe (mismo criterio anti-enumeración del resto del backend).
- Llama a `Documentos.get_vigente(user_id, document_type)` (el documento
  validado más reciente de CUALQUIER proceso anterior del usuario) y a
  `domain.vigencia.es_vigente(validated_at)` para decidir si todavía cae
  dentro de la ventana de 365 días.
- Responde `{"reutilizable": false}` o
  `{"reutilizable": true, "documento": {...}}` (id, tipo, fecha de
  validación, hash). Es una consulta pura — nunca escribe.

#### `confirm_reuse` — `POST /confirm-reuse` (por defecto)
- `@handle_exceptions` + `@require_auth`. Lee `document_type`, `process_id`,
  `source_document_id` del body.
- **No confía en que el cliente haya llamado a `check_reuse` primero**: repite
  todas las validaciones de negocio desde cero —
  - El proceso destino existe y es del usuario.
  - El documento origen (`source_document_id`) existe, y el proceso al que
    pertenece también es del mismo usuario (misma respuesta 404 anti-
    enumeración si no).
  - El origen está `stage == "validado"` y sigue vigente
    (`es_vigente(source.validated_at)`) — si no, `409 documento_no_reutilizable`.
  - El `document_type` declarado coincide con el de la evidencia real — si no,
    `409 document_type_no_coincide_con_el_origen` (guarda agregada en
    revisión de código, antes de abrir PR, no parte del diseño original).
  - El proceso destino no tiene ya un documento `validado` del mismo tipo —
    si lo tiene, `409 proceso_ya_tiene_documento_validado`.
- Si todo pasa: `Documentos.register_reused(...)` crea una fila ya
  `validado`, apuntando a la MISMA `s3_key_evidence` del origen (no copia el
  archivo — la evidencia validada es inmutable), y registra un
  `DocumentEvents` tipo `documento_reutilizado`.

#### `get_status` — `GET /get-status` (por defecto)
- `@handle_exceptions` + `@require_auth`. Lee `process_id` de
  `queryStringParameters`.
- Mismo chequeo de pertenencia que los anteriores (404 anti-enumeración).
- Devuelve `{"process_id", "documentos": [...]}` — el expediente documental
  completo del proceso (`Documentos.list_by_process`), serializado con
  `public_dict()` de cada fila. Es el endpoint que el frontend *polea*
  mientras espera a que `on_upload` termine de procesar una subida — lado de
  consulta del patrón CQRS que separa este handler del comando asíncrono.

#### `on_upload` (worker) — trigger S3 `ObjectCreated:*`, prefijo `transactions/`
Declarado vía `function.yml` propio (no el trigger HTTP por defecto):
`timeout: 60`, `layers: [${cf:cdts-${sls:stage}-tesseract.TesseractLayerArn}]`
(ver 9.4), `environment.TESSDATA_PREFIX: /opt/share/tessdata`. Es el
mecanismo central de C11 — **sin** `@require_auth` (no es invocado por un
cliente HTTP, sino por el propio S3).

`handler(event, context)` itera `event["Records"]`, llama a
`_process_record(record)` por cada uno capturando cualquier excepción (para
que un registro con error no tumbe el procesamiento de los demás del mismo
batch), y al final hace un único `db_session.commit()`.

`_process_record` (pipeline *Functional Core, Imperative Shell* — este
módulo es el *shell* de I/O/orquestación; toda la regla de negocio vive en
`domain.matching`, funciones puras):

1. **Parseo de la key**: `transactions/{process_id}/{document_type}/{uuid}.{ext}`;
   una key fuera de ese esquema se ignora con un log `WARNING`.
2. **Idempotencia**: si `Documentos.get_by_s3_key(key)` ya existe, no reprocesa.
3. Resuelve el proceso (`Processes.get_by_id`) y el nombre declarado
   (`Forms.get_by_user(proc.user_id).full_name`).
4. `Documentos.register_from_s3(...)` crea la fila en `stage="validando"` +
   `DocumentEvents.record(event_type="documento_cargado")`.
5. Descarga los bytes (`libs.core.s3.download_bytes`).
6. **FE1 — formato**: `domain.matching.evaluar_formato(data, content_type)`
   (content-type inferido de la extensión de la key, no del evento S3, que no
   lo trae) — si no es válido, `mark_rechazado(reason="formato_no_admitido")`
   y sale, **sin gastar un ciclo de OCR**.
7. **Extracción**: `TesseractAdapter().extract(data)` (Strategy pattern — es
   la única variable `_extractor` del módulo; el modo cloud con Azure AI
   Document Intelligence se agregaría como otro adaptador sin tocar este
   archivo).
8. **FE1 — legibilidad**: `domain.matching.evaluar_legibilidad(fields)` — si
   no es legible, `mark_rechazado(reason="documento_ilegible")`.
9. **Correspondencia**: `domain.matching.corresponde_con_declarado(fields, nombre_declarado)`
   — si no corresponde, `mark_rechazado(reason="no_corresponde")`.
10. Si todo pasa: calcula `hashlib.sha256(data).hexdigest()`, copia el archivo
    a `evidencia-validada/{...}` (`upload_from_bytes`), y
    `row.mark_validado(s3_key_evidence, hash_sha256)`.
11. En cualquier desenlace, registra un `DocumentEvents` final
    (`documento_validado` o `documento_rechazado` con su motivo) — auditoría
    append-only sin excepción (Q22R01).

### 9.4 El Lambda Layer de Tesseract (`backend/layers/tesseract/`)

Es el mecanismo de despliegue más particular de todo el backend: la única
Lambda Layer real del repo. Nace de una restricción dura del proyecto
(`docs/repo-structure.md` §1: "no hay contenedores") combinada con un hecho
verificado en runtime: `tesseract` no es un paquete de PyPI (no lo resuelve
`serverless-python-requirements`) ni está disponible vía `dnf`/`microdnf` en
Amazon Linux 2023 (confirmado corriendo `dnf repoquery` contra la imagen real
— no existe en ningún repositorio de AL2023). La alternativa de empaquetarlo
como imagen de contenedor se evaluó e implementó primero, pero se revirtió
por violar la regla de "no contenedores"; la Layer es la alternativa 100%
zip.

**`backend/layers/tesseract/serverless.yml`**: un stack *solo-Layer* (sin
funciones propias), `stackName: cdts-${sls:stage}-tesseract`, bloque
`layers.tesseract` con `path: layer`, `name: cdts-${sls:stage}-tesseract`,
`compatibleRuntimes: [python3.12]`. Exporta
`Outputs.TesseractLayerArn = !Ref TesseractLambdaLayer` (la convención de
logical ID de Serverless v3 para una Layer: `<PascalCaseName>LambdaLayer`),
bajo el export name `cdts-${sls:stage}-tesseract-layer-arn` — es lo que
`services/documents/src/workers/on_upload/function.yml` consume vía
`${cf:cdts-${sls:stage}-tesseract.TesseractLayerArn}`.

**Contenido de `layer/`** (committeado como binarios en el repo, no
generado en CI): `bin/tesseract` (ELF, compilado para AL2023), y en `lib/`
los `.so` exactos que `ldd` reportó como faltantes contra la imagen base
`public.ecr.aws/lambda/python:3.12` (`libtesseract.so.5`, `libleptonica.so.6`,
`libjpeg.so.62`, `libpng16.so.16`, `libtiff.so.5`, `libwebp.so.7`,
`libwebpmux.so.3`, `libjbig.so.2.1` — todo lo demás ya vive en la imagen
base, no se re-empaqueta) y `share/tessdata/{eng,spa}.traineddata`. AWS monta
el contenido de una Layer en `/opt` y antepone automáticamente `/opt/bin` a
`PATH` y `/opt/lib` a `LD_LIBRARY_PATH` para **cualquier** Lambda — se
verificó esto empíricamente (no se asumió) corriendo la imagen base real con
`echo $PATH`/`echo $LD_LIBRARY_PATH`, por lo que ni `function.yml` ni el
handler necesitan tocar esas variables.

**`backend/layers/tesseract/build/`** (receta de build reproducible,
Docker usado solo como herramienta local, nunca como runtime desplegado):
- `Dockerfile.build`: compila Tesseract 5.4.1 + Leptonica 1.84.1 desde los
  tarballs oficiales (ambos Apache-2.0) contra una imagen base de Amazon
  Linux 2023, con las dependencias de desarrollo necesarias.
- `Dockerfile.package`: extrae del build anterior exactamente los artefactos
  que van a `layer/`, usando `cp -L` (dereferenciar symlinks) — no `cp -P`,
  porque un entry de symlink dentro de un zip solo guarda el string del
  target, y extractores simples (como `zipfile.extractall()` de Python) no
  lo reconstruyen, produciendo un error `file too short` al cargar la
  librería en runtime. Cada `.so` queda como archivo real bajo su SONAME
  exacto.
- `local-ocr-test.sh` + `ocr_smoke_test.py`: smoke test local (no es parte de
  la suite de pytest — necesita el binario ELF real, que no corre fuera de
  Linux) que monta `layer/` en `/opt` dentro de la imagen base real de
  Lambda y corre `TesseractAdapter` contra una imagen sintética generada con
  Pillow, confirmando end-to-end que el binario + libs + datos de idioma
  funcionan exactamente como lo harían en el Lambda desplegado — sin
  necesitar credenciales de AWS.
- `README.md`: documenta la receta completa y por qué se descartaron las
  Layers de Tesseract de terceros ya publicadas (ninguna mantenida para
  AL2023 + Python 3.12 al momento de construir esta).

### 9.5 Clases y métodos de dominio propios del servicio

**`domain/ports.py`** — el *Anti-Corruption Layer* entre el dominio y
cualquier proveedor de OCR:
- `ExtractedWord` (dataclass frozen): `text: str`, `confidence: float` (0-100),
  `block_num/par_num/line_num: int` — estos tres últimos preservan la
  agrupación por línea real del documento (sin ellos, palabras de líneas
  distintas se concatenarían en el orden de detección de Tesseract, no en el
  orden visual del documento — un bug real encontrado probando con OCR real).
- `ExtractedFields` (dataclass frozen): `words: tuple[ExtractedWord, ...]` —
  la forma única que ve el dominio, sin importar si el proveedor es
  Tesseract o (en un slice futuro) Azure AI Document Intelligence.
- `DocumentExtractor` (`Protocol`, `@runtime_checkable`): el puerto —
  `extract(self, image_bytes: bytes) -> ExtractedFields`. Permite verificar
  con `isinstance()` que tanto `TesseractAdapter` (real) como
  `FakeDocumentExtractor` (doble de prueba) cumplen la misma forma.

**`domain/adapters/tesseract_adapter.py`** — `TesseractAdapter.extract()`:
abre la imagen con PIL, llama a
`pytesseract.image_to_data(image, lang="spa", output_type=Output.DICT)`
(`lang="spa"` es necesario porque una cédula colombiana tiene tildes y eñes
que el modelo de inglés por defecto degrada), y traduce cada entrada del
diccionario nativo de Tesseract a un `ExtractedWord` — incluyendo las
entradas con `conf=-1` (estructurales, sin texto), porque es
`domain.matching.evaluar_legibilidad` quien decide filtrarlas, no el
adaptador (el adaptador solo traduce forma, nunca decide regla de negocio).

**`domain/matching.py`** — función pura (sin boto3, sin ORM, sin I/O),
mismo molde que `services/banks/domain/simulacion.py`:
- `evaluar_formato(data, *, content_type) -> FormatResult`: FE1. Compara los
  *magic bytes* reales del archivo (`_MAGIC_BYTES`, JPEG/PNG) contra lo que
  el content-type declara, y valida que el tamaño esté entre
  `MIN_FILE_SIZE_BYTES` (1024) y `MAX_FILE_SIZE_BYTES` (10 MB). Un solo
  motivo de rechazo (`formato_no_admitido`) cubre las tres causas posibles.
- `evaluar_legibilidad(fields) -> LegibilityResult`: dos condiciones, ambas
  necesarias — al menos `MIN_WORDS_FOR_CONFIDENCE` (5) palabras con texto
  real, Y confianza promedio de esas palabras ≥ `MIN_AVG_CONFIDENCE` (40.0).
  La exclusión de palabras sin texto real existe porque, sin ella, el ruido
  estructural que Tesseract reporta sin texto asociado infla artificialmente
  el promedio (hallazgo real: una imagen de puro ruido daba 95% de confianza
  promedio).
- `_agrupar_por_linea(fields)` (privada): agrupa por
  `(block_num, par_num, line_num)` preservando el orden de aparición.
- `extraer_nombre_probable(fields) -> str | None`: heurística — la línea de
  texto más larga que no sea, en su totalidad, un encabezado conocido
  (`_HEADER_EXCLUDE`, p.ej. "REPUBLICA", "CEDULA", "NIT") ni puramente
  numérica (para no confundir un número de documento con un nombre).
  Limitación conocida y documentada explícitamente como parche, no
  solución estructural — el modo cloud futuro extraería por campo
  estructurado en vez de adivinar por longitud de línea.
- `corresponde_con_declarado(fields, nombre_declarado) -> CorrespondenceResult`:
  usa `rapidfuzz.fuzz.token_sort_ratio` entre el nombre extraído y el
  declarado, con umbral `NAME_MATCH_THRESHOLD` (80.0) — tolera ruido típico
  de OCR (p.ej. sustituciones de caracteres, orden de palabras).

**`domain/vigencia.py`** — FA1, función pura, separada de `matching.py` a
propósito (es una regla temporal sobre metadata, no sobre contenido del
documento): `es_vigente(validated_at, *, ahora=None) -> bool` — compara
contra `VALIDITY_DAYS = 365` (decisión de negocio explícita: una cédula no
vence, pero el expediente KYC del que forma parte sí debe refrescarse).

**`libs/orm/documents.py`** (ORM, documentado también en la sección 7.2 por
consistencia con el resto de modelos, pero descrito en detalle aquí porque
`documents` no está mergeado a `develop` todavía):
- `Documentos` (tabla `documents`): columnas `id`, `process_id` (FK a
  `processes`, `CASCADE`), `document_type`, `stage` (`pendiente|validando|
  validado|rechazado`), `s3_key_raw` (único), `s3_key_evidence`,
  `hash_sha256`, `rejection_reason`, `uploaded_at`, `validated_at`. Métodos:
  `public_dict()`, `get_by_s3_key`, `get_by_id`, `list_by_process`,
  `register_from_s3` (crea en `stage="validando"`), `mark_validado`,
  `mark_rechazado` (valida que el motivo esté en `REJECTION_REASONS`),
  `get_vigente` (join con `Processes`, filtra por usuario + tipo + stage
  validado, ordena por `validated_at desc`), `register_reused` (crea una
  fila ya validada apuntando a la evidencia del documento origen, sin
  copiar el archivo — `s3_key_raw` sintético bajo el prefijo `reused/`).
- `DocumentEvents` (tabla `document_events`): bitácora de auditoría
  append-only (Q22R01) — nunca se actualiza una fila existente. Columnas
  `id`, `document_id` (FK), `event_type`, `actor`, `result`, `created_at`.
  Único método: `record(...)` (siempre inserta una fila nueva).
