# Servicio `banks` — Manual de API (estilo Postman)

Este documento es la referencia de consumo del servicio `banks`
(`backend/services/banks/`): catálogo de bancos, detalle de un banco
(incluida su plantilla de orden de inversión) y simulación de CDT. Pensado
para pegar directo en Postman o Insomnia, o para pegarle con `curl`.

Los ejemplos de response son **capturas reales** contra el stage `staging`
(2026-11-08), recortadas donde se indica.

---

## 1. Base URL

No hay servidor local: todo corre contra un stage desplegado (`dev`,
`staging` o `pro`). La URL sale del output `HttpApiUrl` del stack
`cdts-<stage>-banks`:

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-<stage>-banks \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

No la hardcodees: cambia si el stack se recrea.

---

## 2. Autenticación

**Ninguna.** Los tres endpoints son públicos (no usan `require_auth`). Son
lecturas de catálogo y una simulación sin efectos secundarios.

Además de por HTTP, otros servicios los invocan Lambda-a-Lambda:

| Lambda | La invoca | Para qué |
|---|---|---|
| `simulate` | `processes.create_process` | corroborar la tasa en vez de confiar en el cliente |
| `get_bank` | `files.generate_raw_investment_order` | obtener `io_url`, la plantilla de la orden de inversión |

---

## 3. Endpoints

### 3.1 `GET /banks/get-banks`

Devuelve todos los bancos activos (`is_active = true`), ordenados por
`tier` y luego `name` (para ordenar por tasa usar `simulate`).

**Auth requerida:** no.

**Request**

```http
GET {{base_url}}/banks/get-banks
```

**Response — 200 OK** (recorte: 1 de 12 bancos)

```json
{
  "banks": [
    {
      "id": 11,
      "code": "coltefinanciera",
      "name": "Coltefinanciera",
      "logo_url": "https://cdts-staging-assets.s3.us-east-1.amazonaws.com/banks/coltefinanciera.png",
      "description": "Especialista en CDTs. Las tasas mas altas del mercado.",
      "tier": "AA",
      "rating_by": "BRC Ratings",
      "highlights": ["Las tasas mas altas del mercado", "Especialista en CDTs"]
    }
  ]
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `id` | int | PK en `banks` |
| `code` | string | slug único (`bancolombia`, `nu`, ...) |
| `name` | string | nombre comercial |
| `logo_url` | string | `ASSETS_BASE_URL` + `logo_key`; si `ASSETS_BASE_URL` no está seteada, cae al `logo_key` crudo |
| `description` | string | copy de marketing, una línea |
| `tier` | string | calificación de riesgo (`AAA`, `AA+`, `AA`, ...) |
| `rating_by` | string | agencia calificadora (`Fitch Ratings`, `BRC Ratings`) |
| `highlights` | string[] | bullets cortos para UI (chips); `[]` si el banco no tiene |

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 500 | `internal_server_error` | falla la query (DB caída, etc.); no recibe input, así que no hay 4xx |

**curl**

```bash
curl "{{base_url}}/banks/get-banks"
```

---

### 3.2 `GET /banks/get-bank`

Devuelve un banco por id, con todos los campos de `get-banks` más `io_url`
(la plantilla PDF vacía de la orden de inversión de ese banco) e
`is_active`. Devuelve el banco aunque esté inactivo.

**Auth requerida:** no.

**Request**

```http
GET {{base_url}}/banks/get-bank?bank_id=1
```

| Query param | Tipo | Reglas |
|---|---|---|
| `bank_id` | string entera | requerido |

**Response — 200 OK**

```json
{
  "id": 1,
  "code": "bancolombia",
  "name": "Bancolombia",
  "logo_url": "https://cdts-staging-assets.s3.us-east-1.amazonaws.com/banks/bancolombia.png",
  "io_url": "https://cdts-staging-assets.s3.us-east-1.amazonaws.com/order-forms/bancolombia.pdf",
  "description": "El banco mas grande de Colombia. Cobertura nacional y app lider.",
  "tier": "AAA",
  "rating_by": "Fitch Ratings",
  "highlights": ["La red mas grande del pais", "App lider en Colombia", "Atencion 24/7"],
  "is_active": true
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `io_url` | string \| null | `ASSETS_BASE_URL` + `io_key` (`order-forms/<code>.pdf`); `null` si el banco no tiene plantilla |
| `is_active` | bool | si el banco aparece en `get-banks` y `simulate` |

> Las plantillas viven en el bucket `cdts-<stage>-assets`, bajo
> `order-forms/`. Si falta el PDF de un banco, la generación de la orden
> de inversión de ese banco falla con un 403 al descargarlo.

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid bank_id` | `bank_id` falta o no es entero |
| 404 | `bank_not_found` | no existe un banco con ese id |

**curl**

```bash
curl "{{base_url}}/banks/get-bank?bank_id=1"
```

---

### 3.3 `GET /banks/simulate`

Simula una inversión CDT: dado `amount` + `term`, devuelve solo los bancos
activos cuya banda de monto **y** banda de plazo cubren esos valores, con la
tasa aplicable, ordenados de mejor a peor tasa.

Es `GET` por query params porque es una operación de solo lectura sin
efectos secundarios (cacheable y compartible como URL).

**Auth requerida:** no.

**Request**

```http
GET {{base_url}}/banks/simulate?amount=1000000&term=180
```

| Query param | Tipo | Reglas |
|---|---|---|
| `amount` | string numérica | requerido, > 0 (se castea a `Decimal`) |
| `term` | string entera (días) | requerido, > 0 (se castea a `int`) |

**Response — 200 OK** (recorte: 2 de 11 bancos)

```json
{
  "amount": 1000000.0,
  "term": 180,
  "banks": {
    "12": {
      "code": "nu",
      "name": "Nu Colombia",
      "logo_url": "https://cdts-staging-assets.s3.us-east-1.amazonaws.com/banks/nu.png",
      "description": "El neobanco mas grande del mundo. Experiencia 100% digital.",
      "tier": "AA",
      "rating_by": "Fitch Ratings",
      "highlights": ["El neobanco mas grande del mundo", "Experiencia 100% digital", "Sin letra pequena"],
      "rate": 12.3,
      "interest": 58875.28,
      "final": 1058875.28
    },
    "8": {
      "code": "pichincha",
      "name": "Banco Pichincha",
      "logo_url": "https://cdts-staging-assets.s3.us-east-1.amazonaws.com/banks/pichincha.png",
      "description": "Fuerte en corto plazo con apertura 100% en linea.",
      "tier": "AA+",
      "rating_by": "BRC Ratings",
      "highlights": ["Campeon del corto plazo", "Apertura 100% en linea"],
      "rate": 12.2,
      "interest": 58410.19,
      "final": 1058410.19
    }
  }
}
```

> **`banks` es un objeto, no un array.** La key es el `id` del banco (como
> string) y el valor no repite el `id`. El orden de las keys es el de la
> tasa, de mayor a menor. `processes.create_process` usa esa key para
> buscar el banco elegido.

Cada banco trae los mismos campos que `get-banks` (sin `id`), más:

| Campo | Tipo | Significado |
|---|---|---|
| `rate` | float | tasa efectiva anual (EA %) aplicable a ese `(amount, term)` |
| `interest` | float | interés ganado al final del plazo (COP) |
| `final` | float | `amount + interest` (COP) |

**Bancos que no aparecen:** si un banco no tiene banda de monto o de plazo
que cubra lo pedido, no sale en el objeto (no es un error). Con
`amount=1&term=1`:

```json
{"amount": 1.0, "term": 1, "banks": {}}
```

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid_amount` | `amount` falta, no es numérico, o es ≤ 0 |
| 400 | `invalid_term` | `term` falta, no es entero, o es ≤ 0 |

**curl**

```bash
curl "{{base_url}}/banks/simulate?amount=1000000&term=180"
```

---

## 4. Sobre `integration.py`

Ningún handler de `banks` tiene `integration.py`, y está bien así: por
convención del repo (`docs/repo-structure.md` §13.3) ese test es opcional
y se reserva para endpoints con efectos laterales persistentes o flujos
async. Los tres endpoints de `banks` son de solo lectura; el `test.py`
unitario es suficiente.
