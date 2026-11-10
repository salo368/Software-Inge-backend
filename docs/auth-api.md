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
el stage `dev`, desplegado automáticamente en cada push a `develop`.

Para obtener la URL del API Gateway del stage `dev`:

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-dev-auth \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

Esto devuelve algo como:

```
https://abc123xyz.execute-api.us-east-1.amazonaws.com
```

Esa es tu `{{base_url}}`. Todos los paths de abajo van después de esa URL
(ej. `{{base_url}}/auth/register`).

> En `pro` es lo mismo pero con `--stack-name cdts-pro-auth` (y credenciales
> del deployer de `pro`).

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
  (`bearer_tokens.token_hash`). Si lo perdés, no hay forma de recuperarlo:
  hay que loguear de nuevo.

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
