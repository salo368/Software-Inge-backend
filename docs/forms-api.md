# Servicio `forms` — Manual de API (estilo Postman)

Este documento es la referencia de consumo del servicio `forms`
(`backend/services/forms/`): el formulario de identidad/KYC del usuario
(un formulario por usuario, `user_id` es PK), y el catálogo de
ubicaciones (países y departamentos/ciudades/localidades de Colombia) que
alimenta sus selects. Pensado para pegar directo en Postman o Insomnia, o
para pegarle con `curl`.

Los ejemplos de response de este doc son **capturas reales** contra el
stage `dev`, no datos inventados.

---

## 1. Base URL

No hay servidor local: todo corre contra un stage desplegado (`dev`,
`staging` o `pro`). La URL sale del output `HttpApiUrl` del stack
`cdts-<stage>-forms`:

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-<stage>-forms \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

---

## 2. Autenticación

`upsert-form` y `get-form` requieren `Authorization: Bearer <token>`.
`get-locations` es **público** — es catálogo estático de lectura, sin
razón de negocio para exigir login.

En los endpoints con auth, un token ausente devuelve `401
missing_bearer_token` y uno inválido, revocado o expirado devuelve `401
invalid_or_expired_token` (ver [`auth-api.md`](./auth-api.md) §2).

---

## 3. Endpoints

### 3.1 `PUT /forms/upsert-form`

Valida y guarda el formulario completo del usuario autenticado. Hace
*upsert* real en una sola operación (`INSERT ... ON CONFLICT (user_id) DO
UPDATE`) — la primera llamada crea la fila, cualquier llamada posterior la
actualiza completa. **Todos los campos son obligatorios excepto
`second_name` y `second_last_name`.**

`name`, `second_name`, `last_name` y `second_last_name` se normalizan a
**MAYÚSCULA** antes de guardar, sin excepción (lo que mandes en cualquier
case, vuelve en mayúscula).

**Auth requerida:** sí.

**Request**

```http
PUT {{base_url}}/forms/upsert-form
Authorization: Bearer {{token}}
Content-Type: application/json

{
  "name": "foo", "second_name": "midDle", "last_name": "bar", "second_last_name": "baZ",
  "gender": "M", "birth_date": "1990-05-01",
  "birth_country": "COLOMBIA", "birth_department": "QUINDIO", "birth_city": "ARMENIA",
  "nationality": "COLOMBIA", "email": "curl-form-test@example.com",
  "document_type": "CC", "document_number": "123456789",
  "document_issuance_date": "2010-01-01",
  "document_issuance_country": "COLOMBIA", "document_issuance_department": "CUNDINAMARCA",
  "document_issuance_city": "USAQUEN",
  "phone_ext": "57", "phone_number": "3000000000",
  "civil_status": "SINGLE", "education_level": "PROFESSIONAL",
  "is_pep": false,
  "monthly_income": 1000.0, "monthly_expenses": 500.0,
  "total_assets": 5000.0, "total_liabilities": 0.0,
  "is_tax_declarant": true
}
```

| Campo | Tipo | Reglas |
|---|---|---|
| `name` | string | requerido; se guarda en MAYÚSCULA |
| `second_name` | string | **opcional**; se guarda en MAYÚSCULA si viene |
| `last_name` | string | requerido; se guarda en MAYÚSCULA |
| `second_last_name` | string | **opcional**; se guarda en MAYÚSCULA si viene |
| `gender` | string, enum | requerido: `M`, `F`, `O` |
| `birth_date` | string `YYYY-MM-DD` | requerido |
| `birth_country` | string, código de país | requerido; debe existir en el catálogo de países |
| `birth_department` / `birth_city` | string | requeridos; si `birth_country == "COLOMBIA"` deben ser una ciudad real del catálogo colombiano (si no, texto libre) |
| `nationality` | string, código de país | requerido; debe existir en el catálogo de países |
| `email` | string | requerido; formato válido |
| `document_type` | string, enum | requerido: `CC`, `CE`, `TI`, `PA` |
| `document_number` | string/número | requerido; solo dígitos |
| `document_issuance_date` | string `YYYY-MM-DD` | requerido |
| `document_issuance_country/department/city` | string | mismas reglas que `birth_*`; `document_issuance_city` acepta **localidades** de Bogotá (ej. `USAQUEN`) además de municipios |
| `phone_ext` / `phone_number` | string | requeridos |
| `civil_status` | string, enum | requerido: `SINGLE`, `MARRIED`, `DIVORCED`, `WIDOWED` |
| `education_level` | string, enum | requerido: `NONE`, `PRIMARY`, `SECONDARY`, `TECHNICAL`, `TECHNOLOGICAL`, `PROFESSIONAL`, `POSTGRADUATE` |
| `is_pep` | bool | requerido; debe ser `true`/`false` real, no string |
| `monthly_income` / `monthly_expenses` / `total_assets` / `total_liabilities` | número | requeridos; `>= 0` |
| `is_tax_declarant` | bool | requerido |

**Response — 200 OK** (captura real)

```json
{
  "form": {
    "name": "FOO", "second_name": "MIDDLE", "last_name": "BAR", "second_last_name": "BAZ",
    "gender": "M", "birth_date": "01/05/1990",
    "birth_country": "COLOMBIA", "birth_department": "QUINDIO", "birth_city": "ARMENIA",
    "nationality": "COLOMBIA", "email": "curl-form-test@example.com",
    "document_type": "CC", "document_number": "123456789",
    "document_issuance_date": "01/01/2010",
    "document_issuance_country": "COLOMBIA", "document_issuance_department": "CUNDINAMARCA",
    "document_issuance_city": "USAQUEN",
    "phone_ext": "57", "phone_number": "3000000000",
    "civil_status": "SINGLE", "education_level": "PROFESSIONAL",
    "is_pep": false, "monthly_income": 1000.0, "monthly_expenses": 500.0,
    "total_assets": 5000.0, "total_liabilities": 0.0, "is_tax_declarant": true,
    "updated_at": "2026-11-02 04:06:51.231647+00:00"
  }
}
```

> `birth_date` y `document_issuance_date` vuelven en `dd/mm/yyyy` — es
> formateo de presentación en el handler, la columna real sigue siendo
> `TIMESTAMPTZ`. `updated_at` sí es timestamp completo, es auditoría, no
> input del usuario.

Llamar de nuevo con otros valores (mismo usuario) actualiza la misma
fila — confirmado real: un segundo `upsert-form` cambió `name` y
`updated_at` avanzó.

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `{campo} is required` | falta cualquier campo obligatorio (ej. `gender is required`) |
| 400 | `{campo} must be a non-empty string` | el campo vino pero vacío o no-string |
| 400 | `{campo} must be one of [...]` | enum inválido (`gender`, `document_type`, `civil_status`, `education_level`) |
| 400 | `{campo} must be a valid date (YYYY-MM-DD)` | `birth_date`/`document_issuance_date` con formato distinto |
| 400 | `{campo} must be true or false` | `is_pep`/`is_tax_declarant` no booleano |
| 400 | `{campo} must be a number` / `must be >= 0` | los 4 campos financieros |
| 400 | `{campo} is not a valid country` | `nationality`, `birth_country`, `document_issuance_country` no existen en el catálogo |
| 400 | `document_number must be numeric` | `document_number` con algo que no sea solo dígitos |
| 400 | `email is not valid` | formato de email inválido |
| 400 | `{prefix}_department/{prefix}_city is not valid` | `birth_*`/`document_issuance_*` con país `COLOMBIA` y ciudad que no existe en ese departamento (confirmado real con `MOON_CITY`) |
| 401 | `missing_bearer_token` | sin `Authorization` |

**curl**

```bash
curl -X PUT "{{base_url}}/forms/upsert-form" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ ... (ver payload de arriba) ... }'
```

---

### 3.2 `GET /forms/get-form`

Devuelve el formulario del usuario autenticado, o `null` si todavía no lo
ha llenado (200, no 404 — así el frontend distingue "no llenado" de
"error").

**Auth requerida:** sí.

**Request**

```http
GET {{base_url}}/forms/get-form
Authorization: Bearer {{token}}
```

**Response — 200 OK** (sin formulario, captura real)

```json
{"form": null}
```

**Response — 200 OK** (con formulario) — mismo shape que el `form` de
§3.1.

`processes.set_process_form` también invoca esta Lambda directamente
(Lambda-a-Lambda, reenviando el header `Authorization` del usuario) y
guarda el `form` resultante como `submitted_form` del proceso. Por eso el
`submitted_form` de un proceso tiene exactamente este shape: fechas en
`dd/mm/yyyy` y claves de catálogo (`COLOMBIA`, `SINGLE`...) en vez de
etiquetas.

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 401 | `missing_bearer_token` | sin `Authorization` |

**curl**

```bash
curl "{{base_url}}/forms/get-form" -H "Authorization: Bearer $TOKEN"
```

---

### 3.3 `GET /forms/get-locations`

Catálogo de ubicaciones para los selects del formulario. Un solo
endpoint, dos sabores según `?type=`. Público. Responde con
`Cache-Control: public, max-age=7200` (2h) — es un catálogo estático, no
cambia en runtime.

**Auth requerida:** no.

**Request**

```http
GET {{base_url}}/forms/get-locations?type=countries
```

| Query param | Tipo | Reglas |
|---|---|---|
| `type` | string | requerido: `countries` o `colombian_locations` |

**Response — 200 OK, `type=countries`** (recorte real, catálogo completo
son 196 países)

```json
{
  "data": {
    "COLOMBIA": {"label": "Colombia", "abbr": "CO"},
    "AFGANISTAN": {"label": "Afganistán", "abbr": "AF"},
    "ALBANIA": {"label": "Albania", "abbr": "AL"},
    "ALEMANIA": {"label": "Alemania", "abbr": "DE"},
    "ANDORRA": {"label": "Andorra", "abbr": "AD"}
  }
}
```

**Response — 200 OK, `type=colombian_locations`** (recorte real; la key
de cada país/departamento/ciudad es lo que hay que mandar en
`birth_country`/`birth_department`/`birth_city` etc.)

```json
{
  "data": {
    "ANTIOQUIA": {
      "label": "Antioquia",
      "cities": {
        "ABEJORRAL": {"label": "Abejorral"},
        "ABRIAQUI": {"label": "Abriaquí"},
        "ALEJANDRIA": {"label": "Alejandría"}
      }
    },
    "CUNDINAMARCA": {
      "label": "Cundinamarca",
      "cities": {
        "BOGOTA_DC": {
          "label": "Bogotá D.C.",
          "localities": {
            "USAQUEN": {"label": "Usaquén"},
            "SUBA": {"label": "Suba"},
            "KENNEDY": {"label": "Kennedy"}
          }
        }
      }
    }
  }
}
```

`localities` solo aparece en las pocas ciudades que las tienen (hoy,
Bogotá) — es para `document_issuance_city`, donde la cédula puede
registrar una localidad en vez del municipio. `dane_code` (el código DANE
real) **no** se expone acá a propósito; es un dato interno.

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `Invalid or missing 'type' query parameter. Expected 'colombian_locations' or 'countries'.` | `type` falta o tiene otro valor |

**curl**

```bash
curl "{{base_url}}/forms/get-locations?type=countries"
curl "{{base_url}}/forms/get-locations?type=colombian_locations"
```

---

## 4. Sobre `integration.py`

Ningún handler de `forms` tiene `integration.py` todavía. Por convención
del repo (`docs/repo-structure.md` §13.3) ese test es opcional; el
candidato más claro sería `upsert-form` (escribe en DB), pero el
`test.py` unitario ya cubre la lógica de validación a fondo (42 casos).
