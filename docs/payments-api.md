# Servicio `payments` — Manual de API (estilo Postman)

Este documento es la referencia del servicio `payments`
(`backend/services/payments/`): el registro de las transferencias con que el
usuario paga un CDT. Cada pago es una fila de la tabla `payments` con el
monto y la ruta en S3 del comprobante.

| Lambda | Tipo | Quién la llama |
|---|---|---|
| `get_upload_url` | HTTP `POST /payments/upload-url` | el frontend |
| `create_payment` | HTTP `POST /payments/create-payment` | el frontend |
| `list_process_payments` | interna, sin HTTP | `processes.get_pending_pay` |

Cuándo el proceso queda pagado lo decide `processes`, no este servicio: ver
`GET /processes/get-pending-pay` en [`processes-api.md`](./processes-api.md)
§4.5.

---

## 1. Base URL

No hay servidor local: todo corre contra un stage desplegado (`dev`,
`staging` o `pro`). La URL sale del output `HttpApiUrl` del stack
`cdts-<stage>-payments`:

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-<stage>-payments \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

---

## 2. Autenticación y validación del proceso

Los dos endpoints HTTP requieren `Authorization: Bearer <token>` (ver
[`auth-api.md`](./auth-api.md) §2).

Ambos validan el proceso sin leer la tabla de `processes`: invocan
`processes.get_processes` reenviando el mismo header `Authorization`
(`utils/process_lookup.py`). El proceso debe estar en la lista del usuario y
en stage `PAYMENT`.

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid process id` | `process_id` falta o no es un UUID |
| 404 | `process_not_found` | el proceso no existe o no es del usuario |
| 409 | `process_not_in_payment_stage` | el proceso no está en `PAYMENT` |
| 502 | `processes_unavailable` | falló la invocación a `processes` |
| 401 | `missing_bearer_token` / `invalid_or_expired_token` | token ausente o inválido |

---

## 3. Comprobantes en S3

Los comprobantes van al bucket de `files` (`cdts-<stage>-files`), que es lo
único que comparten los dos servicios, bajo su propio prefijo
(`utils/s3_keys.py`):

```
payments/{process_id}/{uuid}.{ext}
```

El trigger `on_upload` de `files` solo escucha `processes/`, así que un
comprobante no se registra en la tabla `files`. `payments` solo tiene
permiso de escritura sobre `payments/*` en ese bucket.

---

## 4. Endpoints

### 4.1 `POST /payments/upload-url`

Devuelve una URL `PUT` prefirmada (15 min) para subir el comprobante de una
transferencia.

**Request**

```http
POST {{base_url}}/payments/upload-url
Authorization: Bearer {{token}}
Content-Type: application/json

{"process_id": "5798138d-395e-407d-9f92-58858e31a10d", "content_type": "image/png"}
```

| Campo | Reglas |
|---|---|
| `process_id` | requerido; proceso del usuario en `PAYMENT` |
| `content_type` | opcional, default `image/jpeg`; uno de `application/pdf`, `image/jpeg`, `image/png` |

**Response — 200 OK**

```json
{
  "upload_url": "https://cdts-staging-files.s3.amazonaws.com/payments/5798138d-.../0f11b02e-....png?X-Amz-Signature=...",
  "key": "payments/5798138d-395e-407d-9f92-58858e31a10d/0f11b02e-c128-4caf-a76c-7867e82d1165.png",
  "content_type": "image/png",
  "upload_headers": {"Content-Type": "image/png"},
  "expires_in": 900
}
```

Después se sube el archivo con un `PUT` a `upload_url` mandando
`upload_headers`, y el `key` se usa en `create-payment`.

**Errores:** los de §2, más `400 content_type must be one of [...]`.

**curl**

```bash
curl -X PUT "$UPLOAD_URL" -H "Content-Type: image/png" --data-binary @comprobante.png
```

---

### 4.2 `POST /payments/create-payment`

Registra una transferencia: el monto que el usuario dice haber pagado y el
comprobante que ya subió.

**Request**

```http
POST {{base_url}}/payments/create-payment
Authorization: Bearer {{token}}
Content-Type: application/json

{
  "process_id": "5798138d-395e-407d-9f92-58858e31a10d",
  "s3_key": "payments/5798138d-395e-407d-9f92-58858e31a10d/0f11b02e-c128-4caf-a76c-7867e82d1165.png",
  "amount": "1500000"
}
```

| Campo | Reglas |
|---|---|
| `process_id` | requerido; proceso del usuario en `PAYMENT` |
| `s3_key` | requerido; el `key` de `upload-url`. Debe empezar por `payments/{process_id}/` |
| `amount` | requerido; número > 0 (string o número) |

No verifica que el objeto exista en S3: solo que la ruta sea de ese
proceso.

**Response — 200 OK**

```json
{
  "id": "1d6f3b6a-...",
  "process_id": "5798138d-395e-407d-9f92-58858e31a10d",
  "amount": 1500000.0,
  "s3_file": "payments/5798138d-.../0f11b02e-....png"
}
```

**Errores:** los de §2, más:

| status | `error` | Cuándo |
|---|---|---|
| 400 | `s3_key is required` | falta |
| 400 | `s3_key does not belong to this process` | no empieza por `payments/{process_id}/` |
| 400 | `invalid_amount` | falta, no es numérico, o es ≤ 0 |

---

## 5. Lambda interna

### 5.1 `list_process_payments`

Devuelve todos los pagos de un proceso.

**Invocada por:** `processes.get_pending_pay`, de forma síncrona.

**Request** (`event["body"]`, JSON): `{"process_id": "<uuid>"}`. Si falta o
no es UUID, responde `400 invalid process id`.

**Response — 200 OK**

```json
{
  "payments": [
    {"id": "1d6f3b6a-...", "amount": "1500000.00", "s3_file": "payments/5798138d-.../0f11b02e-....png"}
  ]
}
```

`amount` va como texto (no `float`) para que quien sume lo haga en
`Decimal`, sin errores de redondeo.

---

## 6. Tabla `payments`

| Columna | Tipo |
|---|---|
| `id` | `UUID` PK, `gen_random_uuid()` |
| `process_id` | `UUID NOT NULL`, FK a `processes(id)` (`ON DELETE CASCADE`) |
| `amount` | `NUMERIC(15,2) NOT NULL` |
| `s3_file` | `TEXT` |

Modelo: `libs/orm/payments.py`. Migración:
`platform/migrations/sql/20261108000000_create_payments_table.sql`.
