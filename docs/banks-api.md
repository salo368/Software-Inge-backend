# Servicio `banks` — Manual de API (estilo Postman)

Este documento es la referencia de consumo del servicio `banks`
(`backend/services/banks/`): catálogo de bancos y simulación de CDT. Pensado
para pegar directo en Postman o Insomnia, o para pegarle con `curl`.

Los ejemplos de response de este doc son **capturas reales** contra el stage
`dev` (cuenta `658548982073`), no datos inventados.

---

## 1. Base URL

Igual que `auth`: no hay servidor local, todo corre contra `dev` desplegado.

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-dev-banks \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

Al día de escribir este doc, esa URL resuelve a
`https://elrpxpxr10.execute-api.us-east-1.amazonaws.com`. Puede cambiar si el
stack se recrea — siempre resolver con el comando de arriba, no hardcodear.

---

## 2. Autenticación

**Ninguna.** Ambos endpoints son públicos (no usan `require_auth` de `auth`).
Es catálogo de lectura y una simulación sin efectos secundarios — no hay
razón de negocio para exigir login todavía.

---

## 3. Endpoints

### 3.1 `GET /banks/get-banks`

Devuelve todos los bancos activos (`is_active = true`), ordenados por
`tier` y luego `name` (orden alfabético de ambos, no por tasa — para tasa
usar `simulate`).

**Auth requerida:** no.

**Request**

```http
GET {{base_url}}/banks/get-banks
```

**Response — 200 OK** (recorte real, solo los primeros 2 de 12 bancos)

```json
{
  "banks": [
    {
      "id": 11,
      "code": "coltefinanciera",
      "name": "Coltefinanciera",
      "logo_url": "https://cdts-dev-assets.s3.us-east-1.amazonaws.com/banks/coltefinanciera.png",
      "description": "Especialista en CDTs. Las tasas mas altas del mercado.",
      "tier": "AA",
      "rating_by": "BRC Ratings",
      "highlights": ["Las tasas mas altas del mercado", "Especialista en CDTs"]
    },
    {
      "id": 12,
      "code": "nu",
      "name": "Nu Colombia",
      "logo_url": "https://cdts-dev-assets.s3.us-east-1.amazonaws.com/banks/nu.png",
      "description": "El neobanco mas grande del mundo. Experiencia 100% digital.",
      "tier": "AA",
      "rating_by": "Fitch Ratings",
      "highlights": ["El neobanco mas grande del mundo", "Experiencia 100% digital", "Sin letra pequena"]
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
| 500 | `internal_server_error` | falla la query (DB caída, etc.) — no hay errores 4xx posibles, no recibe input |

**curl**

```bash
curl "{{base_url}}/banks/get-banks"
```

---

### 3.2 `GET /banks/simulate`

Simula una inversión CDT: dado `amount` + `term`, devuelve solo los
bancos cuya banda de monto **y** banda de plazo cubren esos valores, con la
tasa aplicable, ordenados de mejor a peor tasa.

Es `GET` por query params (no `POST` con body) porque es una operación de
solo lectura sin efectos secundarios — más coherente con `GET /banks/get-banks`
y cacheable/compartible como URL.

> El campo se llama `term` (no `term_days`) — la unidad siempre fue días en
> todo el backend, el sufijo era redundante. Las capturas de abajo son de
> antes de ese rename; **no están re-verificadas en `dev` todavía**.

**Auth requerida:** no.

**Request**

```http
GET {{base_url}}/banks/simulate?amount=1000000&term=180
```

| Query param | Tipo | Reglas |
|---|---|---|
| `amount` | string numérica | > 0; se castea a `Decimal(str(amount))` — 400 `invalid_amount` si falta, no es numérico o es ≤ 0 |
| `term` | string entera (días) | > 0; se castea a `int(term)` — 400 `invalid_term` si falta, no es entero o es ≤ 0 |

**Response — 200 OK** (captura real previa al rename, `amount=1000000, term=180`; 3 de 12 bancos, recortado)

```json
{
  "amount": 1000000.0,
  "term": 180,
  "banks": [
    {
      "id": 12, "code": "nu", "name": "Nu Colombia",
      "tier": "AA", "rating_by": "Fitch Ratings",
      "rate": 12.3, "interest": 58875.28, "final": 1058875.28
    },
    {
      "id": 8, "code": "pichincha", "name": "Banco Pichincha",
      "tier": "AA+", "rating_by": "BRC Ratings",
      "rate": 12.2, "interest": 58410.19, "final": 1058410.19
    },
    {
      "id": 2, "code": "davivienda", "name": "Davivienda",
      "tier": "AAA", "rating_by": "BRC Ratings",
      "rate": 9.9, "interest": 47654.4, "final": 1047654.4
    }
  ]
}
```

Cada banco trae además `logo_url`, `description`, `highlights` (mismos
campos que `GET /banks/get-banks`), más:

| Campo | Tipo | Significado |
|---|---|---|
| `rate` | float | tasa efectiva anual (EA %) aplicable a ese `(amount, term)` |
| `interest` | float | interés ganado al final del plazo (COP) |
| `final` | float | `amount + interest` (COP) |

**Bancos que no aparecen:** si un banco no tiene una banda de monto o de
plazo que cubra lo pedido, simplemente **no sale en el array** — no es un
error. Confirmado contra un caso extremo real antes del rename (`amount=1, term=1`):

```json
{"amount": 1.0, "term": 1, "banks": []}
```

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid_amount` | `amount` falta, no es numérico, o es ≤ 0 |
| 400 | `invalid_term` | `term` falta, no es entero, o es ≤ 0 |

Confirmado real (antes del rename) con `?amount=-5&term=180` → `400` +
`{"error": "invalid_amount"}`.

**curl**

```bash
curl "{{base_url}}/banks/simulate?amount=1000000&term=180"
```

---

## 4. Sobre `integration.py`

Ningún handler de `banks` tiene `integration.py`, y está bien así: por
convención del repo (`docs/repo-structure.md` §13.3) ese test es opcional
y se reserva para endpoints con efectos laterales persistentes o flujos
async (ej. `auth/register`, que escribe `users`+`user_credentials`). Los
dos endpoints de `banks` son de solo lectura — el `test.py` unitario
mockeado ya es suficiente, no hace falta agregar nada aquí.
