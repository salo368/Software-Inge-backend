# Servicio `processes` — Manual de API (estilo Postman)

Este documento es la referencia de consumo del servicio `processes`
(`backend/services/processes/`): el orquestador del wizard de apertura de
un CDT. Crea el proceso, guarda el formulario, controla los documentos
requeridos, genera la orden de inversión a firmar y avanza cuando la firma
termina. Pensado para pegar directo en Postman o Insomnia, o para pegarle
con `curl`.

Los ejemplos de response son **capturas reales** contra `dev` y `staging`,
recortadas donde se indica.

---

## 1. Base URL

No hay servidor local: todo corre contra un stage desplegado (`dev`,
`staging` o `pro`). La URL sale del output `HttpApiUrl` del stack
`cdts-<stage>-processes`:

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-<stage>-processes \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

---

## 2. Autenticación

Todos los endpoints HTTP requieren `Authorization: Bearer <token>` y solo
operan sobre procesos del usuario autenticado. Excepción: `get-processes` y
`get-process` también aceptan un token de **admin** (backoffice), que no tiene
procesos propios y por eso indica a quién consultar (ver §4.2 y §4.6). Token ausente → `401
missing_bearer_token`; inválido, revocado o expirado → `401
invalid_or_expired_token` (ver [`auth-api.md`](./auth-api.md) §2).

Las lambdas internas de §5 no tienen ruta HTTP: solo se invocan
Lambda-a-Lambda, con permiso de IAM.

---

## 3. Ciclo de vida de un proceso

`processes.stage` (enum `ProcessStage`) avanza así:

| Stage | Lo pone | Cuándo |
|---|---|---|
| `FORM` | `create-process` | al crear el proceso |
| `DOCUMENTS` | `set-process-form` | al guardar el formulario como `submitted_form` |
| `SIGNATURE` | `generate_sign` (interna) | al abrir la firma de la orden de inversión; también guarda `signature_id` |
| `PAYMENT` | `webhooks/signed` (interna) | cuando `signatures` avisa que esa firma quedó `SIGNED` |
| `REVIEW` | `get-pending-pay` | cuando la suma de los pagos cubre el monto del proceso |
| `SENT_TO_BANK` | `send-to-bank` (admin) | cuando backoffice aprueba los pagos de un proceso en `REVIEW` y lo entrega al banco |
| `COMPLETED` | `approve-cdt` (admin) | cuando backoffice aprueba la creación del CDT de un proceso en `SENT_TO_BANK` |

Flujo completo, visto desde el frontend:

1. `POST /processes/create-process` → `FORM`.
2. `PUT /forms/upsert-form` (servicio `forms`) y luego
   `POST /processes/set-process-form` → `DOCUMENTS`.
3. Subir cada documento requerido con `POST /files/upload-url` + `PUT` a S3
   (ver [`files-api.md`](./files-api.md)).
4. Consultar `GET /processes/get-required-files` hasta que todos estén en
   `true`. En esa misma llamada se dispara `generate_sign` en segundo plano.
5. Consultar `GET /processes/get-processes` hasta que el proceso tenga
   `signature_id` (stage `SIGNATURE`; toma unos segundos).
6. Hacer la ceremonia de firma con ese `signature_id` (ver
   [`signatures-api.md`](./signatures-api.md)).
7. Al quedar la firma `SIGNED`, `signatures` invoca `webhooks/signed` y el
   proceso pasa a `PAYMENT`.
8. Por cada transferencia: subir el comprobante con
   `POST /payments/upload-url` + `PUT` a S3, y registrarla con
   `POST /payments/create-payment` (ver [`payments-api.md`](./payments-api.md)).
9. Consultar `GET /processes/get-pending-pay`: devuelve lo que falta por
   pagar y, cuando los pagos cubren el monto, pasa el proceso a `REVIEW`.

---

## 4. Endpoints

### 4.1 `POST /processes/create-process`

Crea un proceso de apertura de CDT en stage `FORM`. Corrobora
`(bank_id, amount, term)` invocando `banks.simulate` directamente
(Lambda-a-Lambda) en vez de confiar en una tasa que mande el cliente: si el
banco no está activo o no tiene una banda que cubra ese `(amount, term)`,
no se crea el proceso. La tasa guardada es la que devuelve `simulate`.

**Auth requerida:** sí.

**Request**

```http
POST {{base_url}}/processes/create-process
Authorization: Bearer {{token}}
Content-Type: application/json

{
  "bank_id": 1,
  "amount": "1000000",
  "term": 180
}
```

| Campo | Tipo | Reglas |
|---|---|---|
| `bank_id` | int | requerido; banco activo con banda de tasa para `(amount, term)` |
| `amount` | string/número | requerido |
| `term` | int (días) | requerido |

**Response — 200 OK**

```json
{
  "id": "6a45941e-bf27-4537-9415-d9e313c5509a",
  "bank_id": 1,
  "amount": 1000000.0,
  "term": 180,
  "rate": 10.1,
  "stage": "FORM",
  "created_at": "2026-11-02 17:55:18.702861+00:00"
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `id` | UUID | PK del proceso |
| `stage` | string | siempre `FORM` al crear |
| `rate` | float | tasa resuelta en el momento, vía `banks.simulate` |
| `created_at` | string | lo pone la DB (`DEFAULT NOW()`) |

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `Missing required fields` | falta `bank_id`, `amount` o `term` |
| 400 | `invalid_amount` / `invalid_term` | propagado tal cual desde `banks.simulate` |
| 400 | `Bank not available for the given amount and term` | el banco no está en el resultado de `simulate` |
| 502 | `simulation_unavailable` | falló la invocación a `banks.simulate` (timeout, etc.) |

**curl**

```bash
curl -X POST "{{base_url}}/processes/create-process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"bank_id": 1, "amount": "1000000", "term": 180}'
```

---

### 4.2 `GET /processes/get-processes`

Lista los procesos del usuario autenticado, más reciente primero.

**Auth requerida:** sí. Acepta token de usuario **o de admin**. Con token de
usuario devuelve siempre los suyos (un `user_id` en la petición se ignora).
Con token de admin hay que indicar `user_id` (query string o body JSON) y
devuelve los de ese usuario; sin él, `400 invalid user id`.

**Request**

```http
GET {{base_url}}/processes/get-processes
Authorization: Bearer {{token}}
```

**Response — 200 OK** (captura de `staging`, 2 procesos)

```json
{
  "processes": [
    {
      "id": "5798138d-395e-407d-9f92-58858e31a10d",
      "bank_id": 1,
      "amount": 3000000.0,
      "term": 365,
      "rate": 11.4,
      "stage": "SIGNATURE",
      "signature_id": "312e7c0b-ace6-44f0-bf09-7ae729a41f30",
      "created_at": "2026-11-08 06:50:56.242646+00:00"
    },
    {
      "id": "d34edeb1-d0ec-42ef-8a54-8d99b368ea84",
      "bank_id": 1,
      "amount": 2500000.0,
      "term": 365,
      "rate": 11.4,
      "stage": "DOCUMENTS",
      "signature_id": null,
      "created_at": "2026-11-08 04:48:03.820035+00:00"
    }
  ]
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `stage` | string | ver §3 |
| `signature_id` | UUID \| null | firma de la orden de inversión; `null` hasta que `generate_sign` la crea |

Usuario sin procesos → `{"processes": []}`, no 404.

**curl**

```bash
curl "{{base_url}}/processes/get-processes" -H "Authorization: Bearer $TOKEN"
```

---

### 4.3 `POST /processes/set-process-form`

Pide al servicio `forms` el formulario del usuario autenticado (invoca
`forms.get_form` Lambda-a-Lambda, reenviando el mismo header
`Authorization`), lo guarda como snapshot en `processes.submitted_form` y
pone el `stage` en `DOCUMENTS`. Si el usuario no ha llenado el formulario,
no cambia nada.

> Solo funciona con el proceso en `FORM` o `DOCUMENTS` (en `DOCUMENTS`
> sirve para reenviar el formulario corregido). Desde `SIGNATURE` en
> adelante responde `409 process_form_locked`: el formulario ya está en una
> firma y no se puede cambiar.

**Auth requerida:** sí.

**Request**

```http
POST {{base_url}}/processes/set-process-form
Authorization: Bearer {{token}}
Content-Type: application/json

{
  "process_id": "6a45941e-bf27-4537-9415-d9e313c5509a"
}
```

| Campo | Tipo | Reglas |
|---|---|---|
| `process_id` | UUID string | requerido; debe ser un proceso del usuario autenticado |

**Response — 200 OK**

```json
{
  "id": "fcdffd0b-02c6-4e66-9ab2-d7cb89467f79",
  "stage": "DOCUMENTS",
  "submitted_form": {
    "name": "FOO", "second_name": "MIDDLE", "last_name": "BAR", "second_last_name": "BAZ",
    "gender": "M", "birth_date": "01/05/1990",
    "birth_country": "COLOMBIA", "birth_department": "QUINDIO", "birth_city": "ARMENIA",
    "nationality": "COLOMBIA", "email": "curl-set-form@example.com",
    "document_type": "CC", "document_number": "123456789",
    "document_issuance_date": "01/01/2010",
    "document_issuance_country": "COLOMBIA", "document_issuance_department": "CUNDINAMARCA",
    "document_issuance_city": "USAQUEN",
    "phone_ext": "57", "phone_number": "3000000000",
    "civil_status": "SINGLE", "education_level": "PROFESSIONAL",
    "is_pep": false, "monthly_income": 1000.0, "monthly_expenses": 500.0,
    "total_assets": 5000.0, "total_liabilities": 0.0, "is_tax_declarant": true,
    "updated_at": "2026-11-02 04:50:22.017363+00:00"
  }
}
```

`submitted_form` es exactamente el `form` que devuelve `GET
/forms/get-form` en ese momento (ver [`forms-api.md`](./forms-api.md)
§3.2). De él salen los documentos requeridos (§4.4) y los datos de la orden
de inversión.

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid process id` | `process_id` falta o no es un UUID válido |
| 404 | `process_not_found` | el proceso no existe o no es del usuario autenticado |
| 400 | `form_required` | el usuario todavía no llenó su formulario (`get_form` devolvió `null`) |
| 409 | `process_form_locked` | el proceso ya pasó de `DOCUMENTS` |
| 502 | `form_lookup_unavailable` | falló la invocación a `forms.get_form` |
| * | (propagado de `get_form`) | si `get_form` responde algo distinto de 200, se reenvía ese status y error |

**curl**

```bash
curl -X POST "{{base_url}}/processes/set-process-form" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"process_id\": \"$PROCESS_ID\"}"
```

---

### 4.4 `GET /processes/get-required-files`

Devuelve qué documentos exige el proceso y cuáles ya están subidos. Lee los
archivos registrados invocando `files.list_process_files`
(Lambda-a-Lambda).

Los documentos requeridos salen del `submitted_form`:

| Documento | Requerido si |
|---|---|
| `BANK_CERT` | siempre |
| `TAX_DECLARATION` | `is_tax_declarant` es `true` |
| `RUT` | `is_pep` es `true` |

> **Efecto lateral:** si todos están subidos y el proceso sigue en
> `DOCUMENTS`, esta misma llamada dispara `generate_sign` en segundo plano
> (§5.1) y responde sin esperarlo. Mientras el proceso siga en `DOCUMENTS`,
> cada llamada vuelve a dispararlo; así un fallo de `generate_sign` se
> reintenta en el siguiente poll. Una vez en `SIGNATURE` ya no se dispara.

**Auth requerida:** sí.

**Request**

```http
GET {{base_url}}/processes/get-required-files?process_id=5798138d-395e-407d-9f92-58858e31a10d
Authorization: Bearer {{token}}
```

| Query param | Tipo | Reglas |
|---|---|---|
| `process_id` | UUID string | requerido; debe ser un proceso del usuario autenticado |

**Response — 200 OK** (declarante de renta y PEP, todo subido)

```json
{"RUT": true, "TAX_DECLARATION": true, "BANK_CERT": true}
```

Solo trae las claves de los documentos requeridos; el orden de las claves
no está garantizado. Con todos en `false`, el proceso todavía espera
documentos.

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid process id` | `process_id` falta o no es un UUID válido |
| 404 | `process_not_found` | el proceso no existe o no es del usuario autenticado |
| 502 | `files_lookup_unavailable` | falló la invocación a `files.list_process_files` |
| * | (propagado de `list_process_files`) | si responde algo distinto de 200, se reenvía ese status y error |
| 502 | `generate_sign_unavailable` | AWS rechazó la invocación asíncrona de `generate_sign` |

**curl**

```bash
curl "{{base_url}}/processes/get-required-files?process_id=$PROCESS_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

### 4.5 `GET /processes/get-pending-pay`

Devuelve cuánto falta por pagar de un proceso en `PAYMENT`. Suma los pagos
registrados invocando `payments.list_process_payments` (Lambda-a-Lambda).

> **Efecto lateral:** si lo pagado cubre `amount` (igual o mayor), esta
> llamada pasa el proceso a `REVIEW`. El `amount` nunca cambia: es el de la
> orden de inversión firmada, así que un pago de más no lo modifica.

**Auth requerida:** sí.

**Request**

```http
GET {{base_url}}/processes/get-pending-pay?process_id=5798138d-395e-407d-9f92-58858e31a10d
Authorization: Bearer {{token}}
```

**Response — 200 OK** (pago parcial)

```json
{
  "process_id": "5798138d-395e-407d-9f92-58858e31a10d",
  "amount": 3000000.0,
  "paid": 1500000.0,
  "pending": 1500000.0,
  "stage": "PAYMENT"
}
```

| Campo | Notas |
|---|---|
| `amount` | el monto del proceso (el de la orden firmada) |
| `paid` | suma de los pagos registrados; puede superar `amount` |
| `pending` | `amount - paid`, nunca negativo (0 al completar el pago) |
| `stage` | `PAYMENT`, o `REVIEW` si esta llamada completó el pago |

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid process id` | `process_id` falta o no es un UUID válido |
| 404 | `process_not_found` | el proceso no existe o no es del usuario autenticado |
| 409 | `process_not_in_payment_stage` | el proceso no está en `PAYMENT` |
| 502 | `payments_unavailable` | falló la invocación a `payments` |
| * | (propagado) | si `payments` responde algo distinto de 200 |

**curl**

```bash
curl "{{base_url}}/processes/get-pending-pay?process_id=$PROCESS_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

### 4.6 `GET /processes/get-process`

Detalle de un proceso.

**Auth requerida:** sí. Acepta token de usuario **o de admin**.

- **Usuario:** solo si el proceso es suyo. Uno ajeno responde igual que uno
  inexistente (`404 process_not_found`), para que no se puedan sondear ids.
- **Admin (backoffice):** cualquier proceso, sin pasar `user_id`.

**Request**

```http
GET {{base_url}}/processes/get-process?process_id=7077c70e-d8bf-4c8e-97ef-a7e0909949df
Authorization: Bearer k3f9s...opaco...
```

`process_id` puede ir en el query string o en un body JSON (el body gana).

**Response — 200 OK**

```json
{
  "process": {
    "id": "7077c70e-d8bf-4c8e-97ef-a7e0909949df",
    "user_id": "c3b1...",
    "bank_id": 1,
    "amount": 1000000.0,
    "term": 180,
    "rate": 12.5,
    "stage": "PAYMENT",
    "signature_id": "312e7c0b-ace6-44f0-bf09-7ae729a41f30",
    "submitted_form": { "name": "Ana", "email": "ana@example.com" },
    "created_at": "2026-11-09 02:34:21+00:00",
    "updated_at": "2026-11-09 22:40:13+00:00"
  }
}
```

**Errores**

| Status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid process id` | falta o no es UUID |
| 401 | `missing_bearer_token` / `invalid_or_expired_token` | token ausente o inválido |
| 404 | `process_not_found` | no existe, o es de otro usuario (token de usuario) |

**curl**

```bash
curl "{{base_url}}/processes/get-process?process_id=$PROCESS_ID"   -H "Authorization: Bearer $TOKEN"
```

---

### 4.7 `POST /processes/get-processes-list`

Backoffice: lista paginada de **todos** los procesos, con filtros y búsqueda.
Es POST porque los filtros viajan en el body. (`get-processes` sigue siendo la
lista de un solo usuario; esta es la del panel.)

**Auth requerida:** sí, **solo token de admin**. Un token de usuario responde
`401 invalid_or_expired_token`.

**Request**

```http
POST {{base_url}}/processes/get-processes-list
Authorization: Bearer <token de admin>
Content-Type: application/json

{
  "search": "ana gomez",
  "bank_id": 1,
  "stages": ["PAYMENT", "REVIEW"],
  "page": 1,
  "page_size": 20
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `search` | string | opcional. Cada palabra debe coincidir con el **inicio** de algún dato principal del `submitted_form`: `name`, `second_name`, `last_name`, `second_last_name`, `email` o `document_number`, sin distinguir mayúsculas. Por eso `"ana gomez"` encuentra a "Ana María Gómez Ruiz", y el orden no importa. Máx. 6 palabras. Los procesos sin formulario (etapa `FORM`) no aparecen cuando hay `search` |
| `bank_id` | int | opcional, ≥ 1 |
| `stages` | string[] | opcional; valores de §3. Por query string va separado por comas (`stages=PAYMENT,REVIEW`) |
| `page` | int | opcional, ≥ 1, default 1 |
| `page_size` | int | opcional, 1–100, default 20 |

Los filtros se combinan con AND. Los más recientes primero. Todos los campos
también se aceptan por query string.

**Response — 200 OK**

```json
{
  "results": [
    {
      "id": "7077c70e-d8bf-4c8e-97ef-a7e0909949df",
      "user_id": "c3b1...",
      "bank_id": 1,
      "amount": 1000000.0,
      "term": 180,
      "rate": 12.5,
      "stage": "PAYMENT",
      "signature_id": "312e7c0b-ace6-44f0-bf09-7ae729a41f30",
      "applicant": {
        "full_name": "Ana María Gómez Ruiz",
        "email": "ana@example.com",
        "document_type": "CC",
        "document_number": "123456789"
      },
      "created_at": "2026-11-09 02:34:21+00:00",
      "updated_at": "2026-11-09 22:40:13+00:00"
    }
  ],
  "count": 1,
  "pagination": { "offset": 0, "limit": 20, "total": 1 }
}
```

`applicant` sale del `submitted_form`; todos sus campos son `null` mientras el
proceso no tenga formulario. `count` es lo de esta página; `total`, lo que
cumple los filtros. Para el detalle de uno, `get-process` (§4.6).

**Errores**

| Status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid_bank_id` / `invalid_stages` / `invalid_search` / `invalid_page` / `invalid_page_size` | valor fuera de rango, de tipo incorrecto, o etapa inexistente |
| 401 | `missing_bearer_token` / `invalid_or_expired_token` | token ausente, inválido, o de usuario |

---

### 4.8 `POST /processes/send-to-bank`

Backoffice: aprueba los pagos de un proceso en `REVIEW` (la suma de los pagos ya cubre el monto) y lo
entrega al banco: `REVIEW` → `SENT_TO_BANK`. Los procesos por aprobar salen de
`get-processes-list` con `stages: ["REVIEW"]`.

**Auth requerida:** sí, **solo token de admin**. Un token de usuario responde
`401 invalid_or_expired_token`.

**Request**

```http
POST {{base_url}}/processes/send-to-bank
Authorization: Bearer <token de admin>
Content-Type: application/json

{ "process_id": "7077c70e-d8bf-4c8e-97ef-a7e0909949df" }
```

**Response — 200 OK**

```json
{ "process_id": "7077c70e-d8bf-4c8e-97ef-a7e0909949df", "stage": "SENT_TO_BANK" }
```

Toma un lock sobre la fila del proceso hasta el commit: si dos admins aprueban
el mismo a la vez, el segundo recibe `409`. Quién aprobó queda en el log de la
lambda (`admin <id> moved process <id> REVIEW -> SENT_TO_BANK`); la tabla `processes` no
guarda auditoría.

**Errores**

| Status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid process id` | falta o no es UUID |
| 401 | `missing_bearer_token` / `invalid_or_expired_token` | token ausente, inválido, o de usuario |
| 404 | `process_not_found` | no existe |
| 409 | `process_not_in_review_stage` | el proceso no está en `REVIEW` (incluye el caso de ya haber sido aprobado) |

**curl**

```bash
curl -X POST "{{base_url}}/processes/send-to-bank"   -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json"   -d '{"process_id": "'$PROCESS_ID'"}'
```

---

### 4.9 `POST /processes/approve-cdt`

Backoffice: aprueba la creación del CDT cuando el banco ya la confirmó: `SENT_TO_BANK` →
`COMPLETED`. Debe haber pasado antes por `send-to-bank`. Los procesos pendientes salen de
`get-processes-list` con `stages: ["SENT_TO_BANK"]`.

**Auth requerida:** sí, **solo token de admin**. Un token de usuario responde
`401 invalid_or_expired_token`.

**Request**

```http
POST {{base_url}}/processes/approve-cdt
Authorization: Bearer <token de admin>
Content-Type: application/json

{ "process_id": "7077c70e-d8bf-4c8e-97ef-a7e0909949df" }
```

**Response — 200 OK**

```json
{ "process_id": "7077c70e-d8bf-4c8e-97ef-a7e0909949df", "stage": "COMPLETED" }
```

Toma un lock sobre la fila del proceso hasta el commit: si dos admins aprueban
el mismo a la vez, el segundo recibe `409`. Quién aprobó queda en el log de la
lambda (`admin <id> moved process <id> SENT_TO_BANK -> COMPLETED`); la tabla `processes` no
guarda auditoría.

**Errores**

| Status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid process id` | falta o no es UUID |
| 401 | `missing_bearer_token` / `invalid_or_expired_token` | token ausente, inválido, o de usuario |
| 404 | `process_not_found` | no existe |
| 409 | `process_not_in_sent_to_bank_stage` | el proceso no está en `SENT_TO_BANK` (incluye el caso de ya haber sido aprobado) |

**curl**

```bash
curl -X POST "{{base_url}}/processes/approve-cdt"   -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json"   -d '{"process_id": "'$PROCESS_ID'"}'
```

---

## 5. Lambdas internas (sin HTTP)

Siguen el mismo contrato que los endpoints: reciben el JSON en
`event["body"]` y responden con `statusCode` + `body` (`handle_exceptions`).
Como se invocan de forma asíncrona, nadie lee esa respuesta; sirve para los
logs y los tests.

### 5.1 `generate_sign` (`src/handlers/generate_sign/`)

Genera la orden de inversión llena, abre la firma sobre ese PDF y guarda el
`signature_id` en el proceso.

**Invocada por:** `get-required-files` (asíncrona), con
`{"body": "{\"process_id\": \"<uuid>\"}"}`.

**Pasos:**

1. Valida que el proceso exista y esté en `DOCUMENTS`.
2. Invoca de forma síncrona `files.generate_raw_investment_order` con
   `process_id`, `bank_id`, `submitted_form`, `amount`, `term` y `rate`,
   todos tomados del proceso. Files devuelve una URL prefirmada del PDF y
   el `sign_location` de la plantilla (ver
   [`files-api.md`](./files-api.md) §4.3).
3. Descarga el PDF por esa URL. No lee el bucket de `files` directamente.
4. Invoca `signatures.create_signature` con el PDF, el `sign_location` y el
   nombre del firmante (nombres y apellidos del `submitted_form`, o
   `Titular` si no hay).
5. Guarda el `signature_id` y pone el proceso en `SIGNATURE`.

**Response — 200 OK**

```json
{"process_id": "5798138d-...", "signature_id": "312e7c0b-..."}
```

**Errores** (el proceso queda en `DOCUMENTS` y el siguiente poll de
`get-required-files` reintenta)

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid process id` | `process_id` falta o no es un UUID |
| 404 | `process_not_found` | el proceso no existe |
| 409 | `process_not_in_documents_stage` | el proceso ya no está en `DOCUMENTS` |
| 502 | `files_unavailable` | falló la invocación a `files` |
| * | (propagado de `files`) | p. ej. `422 bank_without_investment_order`, `502 bank_lookup_failed` |
| 502 | `investment_order_download_failed` | no se pudo bajar el PDF por la URL prefirmada |
| 502 | `signatures_unavailable` | falló la invocación a `signatures` |
| * | (propagado de `create_signature`) | si responde algo distinto de 200 |

> Cada reintento que falle después del paso 2 deja un
> `RAW_INVESTMENT_ORDER` adicional registrado en `files`.

### 5.2 `signed` (`src/webhooks/signed/`)

Recibe el aviso de `signatures` cuando una firma llega a un estado final.

**Invocada por:** `signatures` (`libs/utils/signature_notifications.py`,
asíncrona), con `{"body": "{\"signature_id\": \"<uuid>\", \"stage\": \"SIGNED\"}"}`.
`stage` es `SIGNED` o `FAILED`.

**Comportamiento:**

- Busca el proceso por `signature_id`.
- `SIGNED`: si el proceso está en `SIGNATURE`, lo pasa a `PAYMENT`. Si ya
  avanzó, no hace nada (idempotente).
- `FAILED`: solo registra un WARNING; el proceso se queda en `SIGNATURE`.

**Response — 200 OK**

```json
{"process_id": "5798138d-...", "advanced": true}
```

`advanced` es `false` cuando no hubo transición (firma `FAILED` o proceso
ya avanzado).

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid signature_id` | `signature_id` falta o no es un UUID |
| 400 | `stage must be one of ['SIGNED', 'FAILED']` | `stage` inválido |
| 404 | `process_not_found` | ningún proceso tiene esa firma (p. ej. una firma creada a mano, fuera del flujo) |

---

## 6. Sobre `integration.py`

Ningún handler de `processes` tiene `integration.py` todavía. Por
convención del repo (`docs/repo-structure.md` §13.3) ese test es opcional
y se reserva para flujos con efectos laterales persistentes o
cross-service. Los candidatos más claros son `set-process-form` y la cadena
`get-required-files` → `generate_sign`, que cruzan `forms`, `files` y
`signatures`.
