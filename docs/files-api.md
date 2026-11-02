# Servicio `files` — Manual de API (estilo Postman)

Este documento es la referencia de consumo del servicio `files`
(`backend/services/files/`): subida de archivos de un proceso a S3.
Deliberadamente chico — **2 lambdas en total**: un endpoint HTTP
(`get-upload-url`) y un worker disparado por S3 (`on_upload`), que no se
llama directo.

Los ejemplos de response de este doc son **capturas reales** contra el
stage `dev` (cuenta `658548982073`), no datos inventados — salvo la URL
presignada, que se recorta porque es un blob gigante y ya expiró (TTL de
15 min) para cuando lees esto.

---

## 1. Base URL

Igual que el resto de servicios: no hay servidor local, todo corre contra
`dev` desplegado.

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-dev-files \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

---

## 2. Autenticación

`POST /files/upload-url` requiere `Authorization: Bearer <token>`.

---

## 3. Endpoints

### 3.1 `POST /files/upload-url`

Devuelve una URL PUT presignada de S3 para subir un archivo directo desde
el browser a un proceso del usuario autenticado. No sube nada — solo
firma la URL; la subida real la hace el cliente con un `PUT` aparte
contra esa URL.

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
| `file_type` | string, enum | requerido: `TAX_DECLARATION`, `RUT`, `BANK_CERT`, `INVESTMENT_ORDER` (`libs/orm/files.py::FileType`) |
| `content_type` | string | opcional, default `application/pdf`; uno de `application/pdf`, `image/jpeg`, `image/png` |
| `original_name` | string | opcional; nombre que se le muestra al usuario después (se guarda percent-encoded en metadata S3) |

**Response — 200 OK** (captura real, URL presignada recortada)

```json
{
  "upload_url": "https://cdts-dev-files.s3.amazonaws.com/processes/6a45941e-.../TAX_DECLARATION/0f11b02e-....pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Signature=...",
  "key": "processes/6a45941e-bf27-4537-9415-d9e313c5509a/TAX_DECLARATION/0f11b02e-c128-4caf-a76c-7867e82d1165.pdf",
  "content_type": "application/pdf",
  "upload_headers": {
    "Content-Type": "application/pdf",
    "x-amz-meta-original-name": "curl-test.pdf"
  },
  "expires_in": 900
}
```

| Campo | Notas |
|---|---|
| `upload_url` | PUT directo a esta URL con el body del archivo; válida 900s (`expires_in`) |
| `key` | key real en S3: `processes/{process_id}/{file_type}/{uuid}.{ext}` |
| `upload_headers` | **hay que mandar estos headers exactos** en el `PUT` — son parte de la firma; si no coinciden, S3 rechaza el PUT |

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `process_id and file_type are required` | falta alguno de los dos |
| 400 | `file_type must be one of ['BANK_CERT', 'INVESTMENT_ORDER', 'RUT', 'TAX_DECLARATION']` | `file_type` inválido (confirmado real con `passport` y con el valor viejo en minúscula `tax_declaration` — ya no es válido) |
| 400 | `content_type not allowed` | `content_type` fuera de la lista |
| 400 | `invalid process_id` | `process_id` no es un UUID válido |
| 404 | `process_not_found` | el proceso no existe o no es del usuario autenticado |
| 401 | `missing_bearer_token` | sin `Authorization` |

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
  -H "x-amz-meta-original-name: curl-test.pdf" \
  --data-binary @archivo.pdf
```

Confirmado real: `PUT` → `200`, y `aws s3api head-object` sobre la `key`
devuelve el objeto con el `Content-Type`/metadata correctos.

---

### 3.2 Worker `on_upload` (no es un endpoint HTTP)

Se dispara solo, por `s3:ObjectCreated:*` sobre `cdts-{stage}-files` bajo
el prefijo `processes/`. No se invoca por HTTP ni por `invoke_sync` desde
otro servicio — es puramente un trigger de S3 declarado en
`serverless.yml` (`NotificationConfiguration`).

Parsea la `key` (`processes/{process_id}/{file_type}/{uuid}.{ext}`), lee
el `HEAD` del objeto en S3, y hace `Files.create(...)`. El nombre
original (percent-encoded en la metadata `original-name` que puso
`get-upload-url`) se decodifica ahí.

**Idempotencia:** `files.s3_key` es `UNIQUE` en DB. S3 solo garantiza
*at-least-once*, así que si el mismo evento llega dos veces, el segundo
`Files.create()` revienta el constraint — el `try/except` por-registro
en `handler()` lo atrapa y lo loggea como error, sin tumbar el resto del
batch ni duplicar la fila.

Confirmado real: tras un `PUT` exitoso, CloudWatch de
`/aws/lambda/cdts-dev-files-on-upload` muestra:

```
[INFO] registered file processes/.../TAX_DECLARATION/....pdf for process ...
```

sin reintentos ni errores.

---

## 4. Sobre `integration.py`

`get_upload_url/integration.py` **sí existe** y es el caso de uso típico
para tenerlo: ejercita el flujo completo S3 → worker → DB de punta a
punta (seed de usuario/proceso directo en Postgres, `POST
/files/upload-url`, `PUT` real a S3, poll a la tabla `files` hasta que
`on_upload` registre la fila). Gateado por `--integration`, no corre en
el CI normal — ver `docs/repo-structure.md` §13.3.
