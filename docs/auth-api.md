# Servicio `auth` — Manual de API (estilo Postman)

Este documento es la referencia de consumo del servicio `auth`
(`backend/services/auth/`): qué endpoints existen, cómo autenticarse, y
request/response reales de cada uno. Pensado para pegar directo en Postman o
Insomnia, o para pegarle con `curl`.

Para el *por qué* del diseño (split `users`/`user_credentials`, UUIDs,
bearer tokens con hash) ver el historial de PRs #81/#82 — no hay doc de
arquitectura separado todavía.

---

## 1. Base URL

No hay servidor local (no hay plugin `serverless-offline`). Todo corre contra
un stage desplegado: `dev` (merge a `develop`), `staging` (merge `develop →
staging`) o `pro` (merge a `main`).

La URL del API Gateway de cada stage sale del output `HttpApiUrl` del stack
`cdts-<stage>-auth`:

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-<stage>-auth \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

Esto devuelve algo como:

```
https://abc123xyz.execute-api.us-east-1.amazonaws.com
```

Esa es tu `{{base_url}}`. Todos los paths de abajo van después de esa URL
(ej. `{{base_url}}/auth/register`). No la hardcodees: cambia si el stack se
recrea.

---

## 2. Autenticación

`auth` emite un **bearer token opaco** (no es JWT, es un string random de 32
bytes url-safe). Se manda en cada endpoint protegido así:

```
Authorization: Bearer <token>
```

- Vive 24h desde que se emite (`issue_token`, `TOKEN_DURATION_HOURS = 24`).
- Se puede revocar antes de que expire con `POST /auth/logout`.
- Cada `login` emite un token **nuevo**; los anteriores no se invalidan
  automáticamente (quedan vivos hasta que expiren o se revoquen uno por uno).
- El servidor nunca guarda el token en texto plano, solo su hash SHA-256
  (`user_bearer_tokens.token_hash`). Si lo perdés, no hay forma de recuperarlo:
  hay que loguear de nuevo.

### Tipos de token

Hay dos tipos (`libs/utils/auth.py::AuthsTypes`), cada uno con su propia
tabla de tokens y de sujetos:

| Tipo | Para | Tokens | Sujeto | El handler lo recibe en |
|---|---|---|---|---|
| `USER` | usuarios de la plataforma | `user_bearer_tokens` | `users` | `event["user"]` |
| `INTERNAL` | administradores internos | `admin_bearer_tokens` | `admins` (credenciales en `admin_credentials`) | `event["admin"]` |

Cada handler protegido declara explícitamente qué tipo acepta:

```python
from libs.utils.auth import require_auth, AuthsTypes

@require_auth(AuthsTypes.USER)       # o AuthsTypes.INTERNAL
def handler(event, context): ...
```

Un token de un tipo no existe en la tabla del otro, así que usarlo en un
endpoint del otro tipo responde `401 invalid_or_expired_token`. Escribir
`@require_auth` sin tipo falla al importar el handler (`TypeError`).

Todos los endpoints de este servicio y de los demás son `USER`. Los tokens
`INTERNAL` los emite el servicio `admin_auth` (ver
[`admin-auth-api.md`](./admin-auth-api.md)).

---

## 3. Endpoints

### 3.1 `POST /auth/register`

Crea una cuenta y devuelve un token ya logueado (no hace falta login después
de registrarse).

**Auth requerida:** no.

**Request**

```http
POST {{base_url}}/auth/register
Content-Type: application/json

{
  "email": "ana@example.com",
  "password": "hunter22aa",
  "full_name": "Ana Pérez"
}
```

| Campo | Tipo | Reglas |
|---|---|---|
| `email` | string | formato `x@y.z`, máx 320 chars, se normaliza a lowercase/trim |
| `password` | string | mínimo 10 chars, al menos 1 letra y 1 dígito |
| `full_name` | string | no vacío (se hace `.strip()`) |

**Response — 201 Created**

```json
{
  "user": {
    "id": "3f2a1c0e-...-uuid",
    "email": "ana@example.com",
    "full_name": "Ana Pérez",
    "created_at": "2026-11-01T12:00:00+00:00",
    "updated_at": "2026-11-01T12:00:00+00:00"
  },
  "token": "k3f9s...opaco...",
  "expires_at": "2026-11-02T12:00:00+00:00"
}
```

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `missing_fields` | falta `email`, `password` o `full_name` |
| 400 | `invalid_email` | el email no matchea el formato esperado |
| 400 | `password_required` / `password_too_short` / `password_needs_letter` / `password_needs_digit` | password no cumple las reglas de §3.1 |
| 409 | `email_taken` | ya existe un usuario con ese email |

**curl**

```bash
curl -X POST "{{base_url}}/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"ana@example.com","password":"hunter22aa","full_name":"Ana Pérez"}'
```

---

### 3.2 `POST /auth/login`

Autentica con email+password y emite un token nuevo (no reutiliza tokens
anteriores).

**Auth requerida:** no.

**Request**

```http
POST {{base_url}}/auth/login
Content-Type: application/json

{
  "email": "ana@example.com",
  "password": "hunter22aa"
}
```

**Response — 200 OK**

Mismo shape que `register` (sin el 201):

```json
{
  "user": {
    "id": "3f2a1c0e-...-uuid",
    "email": "ana@example.com",
    "full_name": "Ana Pérez",
    "created_at": "2026-11-01T12:00:00+00:00",
    "updated_at": "2026-11-01T12:00:00+00:00"
  },
  "token": "nuevo-token-opaco",
  "expires_at": "2026-11-02T12:00:00+00:00"
}
```

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `missing_fields` | falta `email` o `password` |
| 401 | `invalid_credentials` | email no existe, o password no matchea el hash |

Nota: por diseño no se distingue "usuario no existe" de "password
incorrecto" — ambos devuelven `invalid_credentials` (anti user-enumeration).

**curl**

```bash
curl -X POST "{{base_url}}/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"ana@example.com","password":"hunter22aa"}'
```

---

### 3.3 `GET /auth/me`

Devuelve el usuario autenticado. Útil para validar que un token sigue vivo.

**Auth requerida:** sí.

**Request**

```http
GET {{base_url}}/auth/me
Authorization: Bearer k3f9s...opaco...
```

**Response — 200 OK**

```json
{
  "user": {
    "id": "3f2a1c0e-...-uuid",
    "email": "ana@example.com",
    "full_name": "Ana Pérez",
    "created_at": "2026-11-01T12:00:00+00:00",
    "updated_at": "2026-11-01T12:00:00+00:00"
  }
}
```

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 401 | `missing_bearer_token` | falta el header `Authorization` o no empieza con `Bearer ` |
| 401 | `invalid_or_expired_token` | el token no existe, fue revocado, o ya expiró |

**curl**

```bash
curl "{{base_url}}/auth/me" \
  -H "Authorization: Bearer k3f9s...opaco..."
```

---

### 3.4 `POST /auth/logout`

Revoca el token con el que se llama (no revoca otros tokens del mismo
usuario).

**Auth requerida:** sí.

**Request**

```http
POST {{base_url}}/auth/logout
Authorization: Bearer k3f9s...opaco...
```

Sin body.

**Response — 200 OK**

```json
{
  "revoked": true
}
```

Después de esto, ese mismo token devuelve `invalid_or_expired_token` en
cualquier endpoint protegido.

**Errores**

Los mismos 401 de `me` (`missing_bearer_token` / `invalid_or_expired_token`)
— si el token ya era inválido, `logout` nunca llega a revocar nada.

**curl**

```bash
curl -X POST "{{base_url}}/auth/logout" \
  -H "Authorization: Bearer k3f9s...opaco..."
```

---

### 3.5 `POST /auth/get-user-list`

Backoffice: lista paginada de usuarios. Es POST porque los filtros viajan en
el body.

**Auth requerida:** sí, **solo token de admin** (`INTERNAL`). Un token de
usuario responde `401 invalid_or_expired_token`.

**Request**

```http
POST {{base_url}}/auth/get-user-list
Authorization: Bearer <token de admin>
Content-Type: application/json

{ "search": "ana", "page": 1, "page_size": 20 }
```

| Campo | Tipo | Notas |
|---|---|---|
| `search` | string | opcional; coincide con el **inicio** de `full_name` o de `email`, sin distinguir mayúsculas. Vacío o ausente = todos |
| `page` | int | opcional, ≥ 1, default 1 |
| `page_size` | int | opcional, 1–100, default 20 |

Los más recientes primero. Los campos también se aceptan por query string.

**Response — 200 OK**

```json
{
  "results": [
    {
      "id": "c3b1...",
      "email": "ana@example.com",
      "full_name": "Ana Gómez",
      "created_at": "2026-11-01T10:00:00",
      "updated_at": "2026-11-01T10:00:00"
    }
  ],
  "count": 1,
  "pagination": { "offset": 0, "limit": 20, "total": 1 }
}
```

`count` es lo que trae esta página; `total` es el total que cumple el filtro.

**Errores**

| Status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid_page` / `invalid_page_size` / `invalid_search` | valor fuera de rango o de tipo incorrecto |
| 401 | `missing_bearer_token` / `invalid_or_expired_token` | token ausente, inválido, o de usuario |

---

### 3.6 `GET /auth/get-user`

Backoffice: un usuario por id.

**Auth requerida:** sí, **solo token de admin**.

**Request**

```http
GET {{base_url}}/auth/get-user?user_id=c3b1...
Authorization: Bearer <token de admin>
```

`user_id` puede ir en el query string o en un body JSON.

**Response — 200 OK**

Mismo objeto `user` que [`/auth/me`](#33-get-authme).

**Errores**

| Status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid user id` | falta o no es UUID |
| 401 | `missing_bearer_token` / `invalid_or_expired_token` | token ausente, inválido, o de usuario |
| 404 | `user_not_found` | no existe |
