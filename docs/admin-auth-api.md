# Servicio `admin_auth` — Manual de API (estilo Postman)

Este documento es la referencia del servicio `admin_auth`
(`backend/services/admin_auth/`): cuentas y sesiones de los administradores
internos. Es el equivalente de [`auth`](./auth-api.md) para admins, con las
mismas cuatro operaciones y una diferencia: **no hay registro abierto**.

- Un admin solo se crea con `POST /admin-auth/register`, y ese endpoint exige
  el token de otro admin.
- El **primer** admin de cada stage se crea con un script que escribe directo
  en la base (§5).

El servicio se llama `admin_auth` como carpeta y en el compose, y `admin-auth`
en AWS: el stack es `cdts-<stage>-admin-auth` y las Lambdas
`cdts-<stage>-admin-auth-<función>`.

---

## 1. Base URL

No hay servidor local: todo corre contra un stage desplegado (`dev`,
`staging` o `pro`). La URL sale del output `HttpApiUrl` del stack
`cdts-<stage>-admin-auth`:

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-<stage>-admin-auth \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

---

## 2. Autenticación

Los tokens de admin son de tipo `INTERNAL` (`AuthsTypes.INTERNAL`, ver
[`auth-api.md`](./auth-api.md) §2) y viven en `admin_bearer_tokens`, aparte
de los de usuario. Se mandan igual:

```
Authorization: Bearer <token>
```

- Un token de usuario **no sirve** en estos endpoints, ni uno de admin en
  los de usuario: cada uno responde `401 invalid_or_expired_token`.
- Vive 24 h y se puede revocar con `POST /admin-auth/logout`.
- Cada `login` emite un token nuevo; los anteriores siguen vivos hasta que
  expiren o se revoquen.

Los demás servicios (forms, processes, files, payments, signatures) siguen
siendo de usuario. Cuando haya endpoints solo para admins, usarán
`@require_auth(AuthsTypes.INTERNAL)`; el admin llega al handler en
`event["admin"]`.

---

## 3. Endpoints

### 3.1 `POST /admin-auth/login`

Autentica a un admin con correo y contraseña y emite un token nuevo.

**Auth requerida:** no.

**Request**

```http
POST {{base_url}}/admin-auth/login
Content-Type: application/json

{"email": "root@example.com", "password": "hunter22aa"}
```

**Response — 200 OK**

```json
{
  "admin": {
    "id": "3f2a1c0e-...-uuid",
    "email": "root@example.com",
    "full_name": "Root Admin",
    "created_at": "2026-11-08T19:30:00+00:00",
    "updated_at": "2026-11-08T19:30:00+00:00"
  },
  "token": "k3f9s...opaco...",
  "expires_at": "2026-11-09T19:30:00+00:00"
}
```

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `missing_fields` | falta `email` o `password` |
| 401 | `invalid_credentials` | el correo no existe o la contraseña no coincide (no se distingue, para no revelar qué correos son admins) |

```bash
curl -X POST "{{base_url}}/admin-auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"root@example.com","password":"hunter22aa"}'
```

---

### 3.2 `GET /admin-auth/me`

Devuelve el admin autenticado.

**Auth requerida:** sí (token de admin).

```http
GET {{base_url}}/admin-auth/me
Authorization: Bearer k3f9s...opaco...
```

**Response — 200 OK**

```json
{
  "admin": {
    "id": "3f2a1c0e-...-uuid",
    "email": "root@example.com",
    "full_name": "Root Admin",
    "created_at": "2026-11-08T19:30:00+00:00",
    "updated_at": "2026-11-08T19:30:00+00:00"
  }
}
```

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 401 | `missing_bearer_token` | falta el header `Authorization` |
| 401 | `invalid_or_expired_token` | el token no existe como token de admin, fue revocado o expiró |

```bash
curl "{{base_url}}/admin-auth/me" -H "Authorization: Bearer $TOKEN"
```

---

### 3.3 `POST /admin-auth/logout`

Revoca el token con el que se llama (no los otros del mismo admin).

**Auth requerida:** sí (token de admin).

```http
POST {{base_url}}/admin-auth/logout
Authorization: Bearer k3f9s...opaco...
```

**Response — 200 OK:** `{"revoked": true}`. Después, ese token responde
`401 invalid_or_expired_token`.

**Errores:** los mismos 401 de `me`.

```bash
curl -X POST "{{base_url}}/admin-auth/logout" -H "Authorization: Bearer $TOKEN"
```

---

### 3.4 `POST /admin-auth/register`

Crea un admin. Solo lo puede llamar un admin autenticado. **No emite
token** para el admin nuevo: ese inicia sesión con `login`.

**Auth requerida:** sí (token de admin).

**Request**

```http
POST {{base_url}}/admin-auth/register
Authorization: Bearer {{token}}
Content-Type: application/json

{"email": "ana@example.com", "password": "hunter22aa", "full_name": "Ana Pérez"}
```

| Campo | Tipo | Reglas |
|---|---|---|
| `email` | string | formato `x@y.z`, máx 320 chars, se normaliza a minúscula |
| `password` | string | mínimo 10 caracteres, al menos 1 letra y 1 dígito |
| `full_name` | string | no vacío |

**Response — 201 Created**

```json
{
  "admin": {
    "id": "9b1d6e3a-...-uuid",
    "email": "ana@example.com",
    "full_name": "Ana Pérez",
    "created_at": "2026-11-08T19:35:00+00:00",
    "updated_at": "2026-11-08T19:35:00+00:00"
  }
}
```

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 401 | `missing_bearer_token` / `invalid_or_expired_token` | sin token de admin (un token de usuario tampoco vale) |
| 400 | `missing_fields` | falta `email`, `password` o `full_name` |
| 400 | `invalid_email` | formato inválido |
| 400 | `password_too_short` / `password_needs_letter` / `password_needs_digit` | la contraseña no cumple las reglas |
| 409 | `email_taken` | ya existe un admin con ese correo |

```bash
curl -X POST "{{base_url}}/admin-auth/register" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email":"ana@example.com","password":"hunter22aa","full_name":"Ana Pérez"}'
```

---

## 4. Tablas

| Tabla | Contenido |
|---|---|
| `admins` | `id`, `email` (único), `full_name`, `created_at`, `updated_at` |
| `admin_credentials` | `admin_id` (PK, FK a `admins`), `password_hash` (bcrypt), `created_at`, `updated_at` |
| `admin_bearer_tokens` | `id`, `admin_id` (FK a `admins`), `token_hash` (SHA-256, único), `expires_at`, `revoked_at`, `created_at` |

Modelos: `libs/orm/admins.py`, `admin_credentials.py` y
`admin_bearer_tokens.py`. Migración:
`platform/migrations/sql/20261108010000_auth_admins.sql`.

---

## 5. Crear el primer admin

Como `register` exige un admin, el primero de cada stage se crea con
`scripts/create-first-admin.py`. Hace falta una credencial AWS que pueda leer
`/cdts/<stage>/db` en SSM (la misma de los otros scripts) y que la base sea
alcanzable desde donde se corre:

```bash
export AWS_PROFILE=cdt AWS_DEFAULT_REGION=us-east-1
python scripts/create-first-admin.py --stage staging \
  --email root@example.com --full-name "Root Admin"
```

- Pide la contraseña dos veces, sin eco. Para automatizar se puede pasar en
  la variable `ADMIN_PASSWORD`. Nunca se imprime; solo se guarda su hash.
- **Se niega a correr si el stage ya tiene algún admin** (sale con código 1
  sin tocar nada). Bloquea la tabla antes de comprobarlo, así que dos
  ejecuciones simultáneas no pueden crear dos.
- No va en una migración a propósito: el hash de la contraseña quedaría en
  git.
