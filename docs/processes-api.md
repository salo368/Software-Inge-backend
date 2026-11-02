# Servicio `processes` — Manual de API (estilo Postman)

Este documento es la referencia de consumo del servicio `processes`
(`backend/services/processes/`): apertura del flujo de CDT, listado de
procesos del usuario, y el paso que engancha el formulario (`forms`) a un
proceso. Pensado para pegar directo en Postman o Insomnia, o para pegarle
con `curl`.

Los ejemplos de response de este doc son **capturas reales** contra el
stage `dev` (cuenta `658548982073`), no datos inventados.

---

## 1. Base URL

Igual que `auth`/`banks`: no hay servidor local, todo corre contra `dev`
desplegado.

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-dev-processes \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

Esa URL puede cambiar si el stack se recrea — siempre resolver con el
comando de arriba, no hardcodear.

---

## 2. Autenticación

**Los 3 endpoints requieren `Authorization: Bearer <token>`** (token de
`auth/login` o `auth/register`). No hay endpoints públicos en este
servicio.

---

## 3. Endpoints

### 3.1 `POST /processes/create-process`

Crea un proceso de apertura de CDT. Corrobora `(amount, term, bank_id)`
contra las bandas de tasa vigentes invocando `banks.simulate` directamente
(Lambda-a-Lambda), en vez de confiar en una tasa que mande el cliente — si
el banco no tiene una banda que cubra ese `(amount, term)`, no se crea el
proceso. Queda en stage `FORM`.

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
| `bank_id` | int | requerido; debe tener una banda de tasa vigente para `(amount, term)` |
| `amount` | string/número | requerido |
| `term` | int (días) | requerido |

**Response — 200 OK** (captura real)

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
| `stage` | string | siempre `FORM` al crear (enum `process_stage` en DB) |
| `rate` | float | tasa resuelta en el momento, vía `banks.simulate` |
| `created_at` | string | lo pone la DB (`DEFAULT NOW()`), no el handler |

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `Missing required fields` | falta `bank_id`, `amount` o `term` |
| 400 | `invalid_amount` / `invalid_term` / etc. | el que devuelva `banks.simulate` tal cual, propagado |
| 400 | `Bank not available for the given amount and term` | `bank_id` no tiene banda para ese `(amount, term)` |
| 502 | `simulation_unavailable` | falló la invocación a `banks.simulate` (timeout, etc.) |
| 401 | `missing_bearer_token` | sin `Authorization` |

**curl**

```bash
curl -X POST "{{base_url}}/processes/create-process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"bank_id": 1, "amount": "1000000", "term": 180}'
```

---

### 3.2 `GET /processes/get-processes`

Lista los procesos del usuario autenticado, más reciente primero.

**Auth requerida:** sí.

**Request**

```http
GET {{base_url}}/processes/get-processes
Authorization: Bearer {{token}}
```

**Response — 200 OK** (captura real, 2 procesos)

```json
{
  "processes": [
    {
      "id": "99583614-166f-488b-93cd-18777e3c9346",
      "bank_id": 2,
      "amount": 2000000.0,
      "term": 180,
      "rate": 9.9,
      "stage": "FORM",
      "created_at": "2026-11-02 01:25:57.757895+00:00"
    },
    {
      "id": "45e6d154-3af2-4b0d-bb32-b6961063ebb3",
      "bank_id": 1,
      "amount": 1000000.0,
      "term": 180,
      "rate": 10.1,
      "stage": "FORM",
      "created_at": "2026-11-02 01:25:54.796015+00:00"
    }
  ]
}
```

Usuario sin procesos → `{"processes": []}`, no 404.

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 401 | `missing_bearer_token` | sin `Authorization` |

**curl**

```bash
curl "{{base_url}}/processes/get-processes" -H "Authorization: Bearer $TOKEN"
```

---

### 3.3 `POST /processes/set-process-form`

Toma el proceso indicado, pide al servicio `forms` el formulario del
usuario autenticado (invoca `forms.get_form` Lambda-a-Lambda, reenviando
el mismo header `Authorization` recibido), y si existe lo guarda como
snapshot en `processes.submitted_form` y avanza `stage` a `DOCUMENTS`. Si
el usuario no ha llenado el formulario todavía, no avanza nada.

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

**Response — 200 OK** (captura real)

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
/forms/get-form` en ese momento — ver [`forms-api.md`](./forms-api.md)
§3.2 para el detalle de cada campo.

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid process id` | `process_id` falta o no es un UUID válido |
| 404 | `process_not_found` | el proceso no existe o no es del usuario autenticado |
| 400 | `form_required` | el usuario todavía no llenó su formulario (`get_form` devolvió `null`) |
| 502 | `form_lookup_unavailable` | falló la invocación a `forms.get_form` (timeout, etc.) |
| * | (propagado de `get_form`) | si `get_form` devuelve algo distinto de 200, ese mismo status/error se reenvía tal cual |
| 401 | `missing_bearer_token` | sin `Authorization` |

**curl**

```bash
curl -X POST "{{base_url}}/processes/set-process-form" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"process_id\": \"$PROCESS_ID\"}"
```

---

## 4. Sobre `integration.py`

Ninguno de los 3 handlers tiene `integration.py` todavía. Por convención
del repo (`docs/repo-structure.md` §13.3) ese test es opcional y se
reserva para flujos con efectos laterales persistentes relevantes o
cross-service — `set-process-form` es el candidato más claro (escribe en
`processes` después de invocar `forms` de verdad), por si se agrega más
adelante.
