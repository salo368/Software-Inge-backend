# Servicio `files` — Manual de API (estilo Postman)

Este documento es la referencia del servicio `files`
(`backend/services/files/`): los archivos de cada proceso en S3, su
registro en la tabla `files` y la generación de la orden de inversión
llena. Tiene 4 lambdas:

| Lambda | Tipo | Quién la llama |
|---|---|---|
| `get_upload_url` | HTTP `POST /files/upload-url` | el frontend |
| `on_upload` | trigger de S3 (`workers/`) | S3, al crear un objeto bajo `processes/` |
| `list_process_files` | interna, sin HTTP | `processes.get_required_files` |
| `generate_raw_investment_order` | interna, sin HTTP | `processes.generate_sign` |

Y dos utilidades propias del bloque, en `services/files/utils/`:

| Módulo | Qué hace |
|---|---|
| `s3_keys.py` | única fuente de la convención de rutas del bucket y de la metadata de cada objeto (§3) |
| `investment_order.py` | llena la plantilla PDF de la orden de inversión de un banco (§4.3) |

Los ejemplos de response son capturas reales, salvo las URLs prefirmadas,
que se recortan (son largas y expiran a los 15 min).

---

## 1. Base URL

No hay servidor local: todo corre contra un stage desplegado (`dev`,
`staging` o `pro`). La URL sale del output `HttpApiUrl` del stack
`cdts-<stage>-files`:

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-<stage>-files \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

---

## 2. Autenticación

`POST /files/upload-url` requiere `Authorization: Bearer <token>` (ver
[`auth-api.md`](./auth-api.md) §2). Las lambdas internas solo se invocan
Lambda-a-Lambda, con permiso de IAM.

---

## 3. Rutas y metadata en S3

Todo vive en el bucket `cdts-<stage>-files`. Las rutas y la metadata se
arman **solo** con `utils/s3_keys.py`, para que mover una lambda no cambie
la convención:

| Función | Resultado |
|---|---|
| `build_file_key(process_id, file_type, file_id, ext)` | `processes/{process_id}/{file_type}/{file_id}{ext}` |
| `build_file_metadata(process_id, file_type, original_name)` | `{"process-id", "file-type", "original-name"}` |

Ningún código extrae datos de la ruta. `on_upload` registra cada archivo a
partir de la metadata del objeto, y la ruta solo se guarda como `s3_key`.

Tipos de archivo (`libs/orm/files.py::FileType`):

| `file_type` | Origen |
|---|---|
| `BANK_CERT`, `TAX_DECLARATION`, `RUT` | los sube el usuario (cuáles exige el proceso: ver [`processes-api.md`](./processes-api.md) §4.4) |
| `INVESTMENT_ORDER` | lo sube el usuario |
| `RAW_INVESTMENT_ORDER` | lo genera el servidor (§4.3): la orden llena, antes de firmar |

---

## 4. Endpoints y lambdas

### 4.1 `POST /files/upload-url`

Devuelve una URL `PUT` prefirmada de S3 para subir un archivo directo desde
el browser a un proceso del usuario autenticado. No sube nada: la subida
real la hace el cliente con un `PUT` aparte contra esa URL.

**Auth requerida:** sí.

**Request**

```http
POST {{base_url}}/files/upload-url
Authorization: Bearer {{token}}
Content-Type: application/json

{
  "process_id": "6a45941e-bf27-4537-9415-d9e313c5509a",
  "file_type": "TAX_DECLARATION",
  "content_type": "application/pdf",
  "original_name": "curl-test.pdf"
}
```

| Campo | Tipo | Reglas |
|---|---|---|
| `process_id` | UUID string | requerido; debe ser un proceso del usuario autenticado |
| `file_type` | string, enum | requerido; cualquier valor de `FileType` (§3) |
| `content_type` | string | opcional, default `application/pdf`; uno de `application/pdf`, `image/jpeg`, `image/png` |
| `original_name` | string | opcional; nombre que se le muestra al usuario después (se guarda percent-encoded en la metadata) |

**Response — 200 OK** (URL prefirmada recortada)

```json
{
  "upload_url": "https://cdts-dev-files.s3.amazonaws.com/processes/6a45941e-.../TAX_DECLARATION/0f11b02e-....pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Signature=...",
  "key": "processes/6a45941e-bf27-4537-9415-d9e313c5509a/TAX_DECLARATION/0f11b02e-c128-4caf-a76c-7867e82d1165.pdf",
  "content_type": "application/pdf",
  "upload_headers": {
    "Content-Type": "application/pdf",
    "x-amz-meta-process-id": "6a45941e-bf27-4537-9415-d9e313c5509a",
    "x-amz-meta-file-type": "TAX_DECLARATION",
    "x-amz-meta-original-name": "curl-test.pdf"
  },
  "expires_in": 900
}
```

| Campo | Notas |
|---|---|
| `upload_url` | `PUT` directo a esta URL con el archivo como body; válida 900 s (`expires_in`) |
| `key` | ruta real en S3 (§3) |
| `upload_headers` | **hay que mandar todos estos headers, exactos,** en el `PUT`. Son parte de la firma: si falta alguno, S3 responde `403 SignatureDoesNotMatch`. Los `x-amz-meta-*` son la metadata con la que `on_upload` registra el archivo |

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `process_id and file_type are required` | falta alguno de los dos |
| 400 | `file_type must be one of ['BANK_CERT', 'INVESTMENT_ORDER', 'RAW_INVESTMENT_ORDER', 'RUT', 'TAX_DECLARATION']` | `file_type` inválido |
| 400 | `content_type not allowed` | `content_type` fuera de la lista |
| 400 | `invalid process_id` | `process_id` no es un UUID válido |
| 404 | `process_not_found` | el proceso no existe o no es del usuario autenticado |
| 401 | `missing_bearer_token` / `invalid_or_expired_token` | token ausente o inválido |

**curl — pedir la URL**

```bash
curl -X POST "{{base_url}}/files/upload-url" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"process_id": "'"$PROCESS_ID"'", "file_type": "TAX_DECLARATION", "content_type": "application/pdf", "original_name": "curl-test.pdf"}'
```

**curl — subir el archivo con la URL que devolvió lo anterior**

```bash
curl -X PUT "$UPLOAD_URL" \
  -H "Content-Type: application/pdf" \
  -H "x-amz-meta-process-id: $PROCESS_ID" \
  -H "x-amz-meta-file-type: TAX_DECLARATION" \
  -H "x-amz-meta-original-name: curl-test.pdf" \
  --data-binary @archivo.pdf
```

Respuesta esperada: `200` con body vacío.

---

### 4.2 `on_upload` (trigger de S3, sin HTTP)

Se dispara solo, por `s3:ObjectCreated:*` sobre `cdts-<stage>-files` bajo
el prefijo `processes/`. Está declarado en `serverless.yml`
(`NotificationConfiguration`); no se invoca desde otro servicio.

Lee el `HEAD` del objeto y hace `Files.create(...)` con su metadata:

| Metadata | Regla |
|---|---|
| `process-id` | obligatoria, UUID válido |
| `file-type` | obligatoria, valor de `FileType` |
| `original-name` | opcional, percent-encoded; se decodifica antes de guardar (`null` si falta) |

Si falta `process-id` o `file-type`, o son inválidos, el objeto se ignora
con un WARNING y no se registra. También guarda `size_bytes` y
`content_type` del `HEAD`.

**Idempotencia:** `files.s3_key` es `UNIQUE`. S3 solo garantiza entrega
*at-least-once*, así que si el mismo evento llega dos veces el segundo
insert choca con el constraint; el `try/except` por registro lo deja en el
log sin tumbar el resto del lote ni duplicar la fila.

---

### 4.3 `generate_raw_investment_order` (interna, sin HTTP)

Llena la plantilla de la orden de inversión del banco con el formulario y
las condiciones del CDT, la sube al bucket como `RAW_INVESTMENT_ORDER` y
devuelve una URL prefirmada para descargarla. Es el PDF que después se
firma.

**Invocada por:** `processes.generate_sign`, de forma síncrona.

**Request** (`event["body"]`, JSON)

```json
{
  "process_id": "5798138d-395e-407d-9f92-58858e31a10d",
  "bank_id": 1,
  "submitted_form": { "...": "el submitted_form del proceso" },
  "amount": "3000000",
  "term": 365,
  "rate": "11.4"
}
```

| Campo | Reglas |
|---|---|
| `process_id`, `bank_id`, `submitted_form` | requeridos |
| `amount`, `term`, `rate` | requeridos; salen del proceso, no del formulario |

**Pasos:**

1. Invoca `banks.get_bank` para obtener `io_url`, la plantilla del banco.
2. Descarga la plantilla y la llena con `utils/investment_order.py`.
3. La sube con `build_file_key` + `build_file_metadata` (§3). La fila en
   `files` la crea `on_upload` a partir de esa metadata, no esta lambda.

**Response — 200 OK**

```json
{
  "process_id": "5798138d-395e-407d-9f92-58858e31a10d",
  "key": "processes/5798138d-.../RAW_INVESTMENT_ORDER/737513df-....pdf",
  "url": "https://cdts-staging-files.s3.amazonaws.com/processes/...?X-Amz-Signature=...",
  "sign_location": [{"page": 1, "x_pct": 8.0, "y_pct": 80.0, "width_pct": 40.0, "height_pct": 14.0}]
}
```

| Campo | Notas |
|---|---|
| `url` | GET prefirmado (15 min). Los otros servicios bajan el PDF por aquí, nunca leyendo este bucket directamente |
| `sign_location` | dónde va la firma en esa plantilla, en el formato que espera `signatures.create_signature` |

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `process_id, bank_id and submitted_form are required` | falta alguno |
| 400 | `amount, term and rate are required` | falta alguno |
| 502 | `bank_lookup_failed` | `banks.get_bank` respondió distinto de 200 |
| 422 | `bank_without_investment_order` | el banco no tiene `io_url` |
| 500 | `internal_server_error` | p. ej. la plantilla no existe en el bucket de assets (403 al descargarla) |

**Cómo se llena la plantilla** (`utils/investment_order.py`):

- Las 12 plantillas comparten el mismo layout, así que los valores se
  dibujan como texto en coordenadas fijas; no tienen campos de formulario.
- Países, departamentos y ciudades se traducen a su etiqueta con
  `libs/utils/locations.py` (`Location`, `IssuanceLocation`, `Countries`):
  `QUINDIO` → `Quindío`, `USAQUEN` → `Usaquén`. Si una clave no está en el
  catálogo, se imprime tal cual.
- `civil_status` y `education_level` se traducen con un diccionario propio
  del bloque (`SINGLE` → `Soltero(a)`, `PROFESSIONAL` → `Profesional`...).
  No se importa el ORM de `forms`: si cambian esos enums, hay que
  actualizar el diccionario a mano.
- Montos en formato `$ 1,000,000`, plazo en días, tasa en `% E.A.` y fecha
  de apertura del día.
- Las casillas de declarante de renta y PEP se marcan con una `X`.

---

### 4.4 `list_process_files` (interna, sin HTTP)

Devuelve todos los archivos registrados de un proceso, más reciente
primero.

**Invocada por:** `processes.get_required_files`, de forma síncrona.

**Request:** `{"process_id": "<uuid>"}` directo en el evento (no dentro de
`body`).

**Response — 200 OK**

```json
{
  "files": [
    {
      "id": "1d6f3b6a-...",
      "file_type": "RAW_INVESTMENT_ORDER",
      "original_name": "investment_order.pdf",
      "uploaded_at": "2026-11-08 04:48:07.120543+00:00"
    }
  ]
}
```

---

## 5. Sobre `integration.py`

`get_upload_url/integration.py` existe y ejercita el flujo completo S3 →
`on_upload` → DB: crea usuario y proceso directo en Postgres, pide
`POST /files/upload-url`, hace el `PUT` real a S3 y consulta la tabla
`files` hasta que `on_upload` registre la fila. Corre solo con
`--integration` (ver `docs/repo-structure.md` §13.3).
