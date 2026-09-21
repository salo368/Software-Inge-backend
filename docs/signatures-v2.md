# Servicio `signatures` — Referencia técnica (v2)

Este documento cubre el servicio genérico de firma digital que vive en
`backend/services/signatures/`. Está pensado para dos audiencias:

- Devs del equipo que integran otro servicio (hoy `processes`, mañana lo que sea)
  con `signatures`.
- Ops que bootstrapean el ambiente por primera vez o rotan credenciales.

Para el contexto teórico legal/criptográfico ver
[`arquitectura_firma_digital_colombia_resumen.md`](./arquitectura_firma_digital_colombia_resumen.md).
Para la estructura del repo y las reglas de deploy selectivo ver
[`repo-structure.md`](./repo-structure.md).

---

## 1. Objetivo

`signatures` es un servicio **agnóstico al dominio**. No sabe qué es un CDT, un
proceso, un banco ni un formulario. Solo sabe firmar PDFs y guardar evidencia.

El consumidor le entrega un PDF (vía URL prefirmado) + coordenadas donde va la
firma + un email; `signatures` conduce al firmante por una ceremonia web
(microfrontend público), captura evidencia (ID + selfie + garabato +
consentimiento + OTP), firma criptográficamente el PDF con **PAdES-B baseline**
usando un certificado efímero emitido por una **CA mock interna**, y notifica el
resultado (webhook o polling). El paquete de evidencia y el PDF firmado quedan
en un bucket S3 propio del servicio, listos para descarga y verificación.

Explícitamente **NO** hace:

- Autenticar usuarios (eso es de `auth`).
- Guardar datos de negocio del consumidor.
- Compartir bucket con `files` ni con ningún otro servicio.
- Depender de que el firmante tenga cuenta en la plataforma (el link de firma
  se abre por email, no requiere login).

---

## 2. Topología

```text
┌────────────┐     invoke     ┌──────────────┐    presigned URL    ┌────────┐
│ processes  ├───────────────►│  signatures  │◄────────────────────┤ signer │
│  (bridge)  │  (X-Service-   │              │  microfrontend       │ (email │
└─────┬──────┘     Key)       │   * Lambdas  │  firmando el PDF     │  link) │
      │                       │   * S3       └──────────┬──────────┘   │    │
      │ webhook               │   * SSM                 │              │    │
      │ callback              │   * Rekognition         │              │    │
      │ POST                  │                          │              │    │
      ▼                       └──────────────────────────┘              │    │
┌────────────┐                          │                                │    │
│ processes  │                          │ direct S3 PUT via presigned   │    │
│ signature_ │◄─────────────────────────┘  (upload_url)                 │    │
│ callback   │                                                           │    │
└────────────┘                                                           │    │
                                                                         │    │
                                       ┌──── OTP email ──────────────────┘    │
                                       │                                       │
                                       ▼                                       │
                                    SMTP/SES ──────────────────────────────────┘
```

Un ciclo de vida completo tiene tres partes:

1. **Apertura (M2M).** El consumidor (hoy `processes`) llama `signatures.create`
   con `X-Service-Key`. Recibe `sign_id` + `sign_url` (el URL del
   microfrontend).
2. **Ceremonia (link-based).** El firmante abre `sign_url`, sube ID front/back,
   selfie, garabato, acepta consentimiento, pide OTP, lo verifica. Todo por
   endpoints públicos autenticados por el `sign_id` que viaja en el path.
3. **Firma + notificación.** Al verificar OTP, `signatures` dispara una Lambda
   interna async (`sign`) que estampa, firma con PAdES-B y hace POST del
   resultado al `callback_url` (si el consumidor lo configuró); si no, el
   consumidor hace polling contra `signatures.get`.

---

## 3. Ciclo de vida de la ceremonia

Máquina de estados de la fila `signatures.stage`:

```text
   created ──► identity ──► consent ──► otp ──► signing ──► signed
      │           │            │         │         │
      ▼           ▼            ▼         ▼         ▼
   expired    expired      expired   failed     failed
```

| Stage | Transición desde | Producida por | Notas |
|---|---|---|---|
| `created` | (inicial) | `create` | Ceremony recién abierta; `hash_original` calculado, PDF ya en S3. |
| `identity` | `created` | `attach_evidence` de los tres endpoints de validación (front/back/face) al pasar | Se marca cuando **los tres** evidences quedaron validados. |
| `consent` | `identity` | `consent` | El firmante aceptó los términos (`terms_version`). |
| `otp` | `consent`, `otp` (resend) | `request_otp` | Idempotente en resend: sobrescribe el hash del OTP y su expiry. |
| `signing` | `otp` | `verify_otp` | OTP correcto; dispara la invocación async de `sign`. |
| `signed` | `signing` | `sign` (worker) | PDF firmado y subido a S3; evidence package generado. |
| `failed` | cualquiera | `sign` (worker) o `verify_otp` cuando se agotan intentos | Terminal. |
| `expired` | cualquiera no-terminal | GET/POST que detectan `expires_at < now` | Terminal; ceremony vence 24h después de `create`. |

Reglas de guarda:

- **`ensure_stage_allows(row, allowed)`** vive en `services/signatures/utils/auth.py`
  y es la única forma correcta de proteger un endpoint. Rechaza con `409 Conflict`
  para stages no permitidos y con `410 Gone` para `signed`, `failed`, `expired`.
- Ninguna transición retrocede. `otp → consent` no existe.
- El firmante puede reabrir el link cuantas veces quiera mientras la ceremony
  esté en un stage no terminal; el frontend inspecciona `signatures.get` y
  posiciona al usuario en el step correcto.

---

## 4. Endpoints — referencia rápida

Todos viven bajo `/signatures/*` sobre HTTP API v2. La columna "auth" indica el
mecanismo (§5):

| Método | Path | Auth | Handler | Comentario |
|---|---|---|---|---|
| POST | `/signatures` | `X-Service-Key` (M2M) | `create` | Abre la ceremony. Devuelve `sign_id` + `sign_url`. |
| GET | `/signatures/{sign_id}` | `sign_id` en path | `get` | Vista pública de la ceremony para el microfrontend. Devuelve un presigned GET del PDF original (15 min). |
| POST | `/signatures/{sign_id}/upload-url` | `sign_id` | `upload_url` | Presigned PUT (5 min) a una key controlada según `evidence_type` (`id_front`, `id_back`, `face`, `signature`). |
| POST | `/signatures/{sign_id}/evidence/id-front` | `sign_id` | `validate_id_front` | Rekognition DetectText + heurística (>=3 líneas legibles, >=6 dígitos totales). |
| POST | `/signatures/{sign_id}/evidence/id-back` | `sign_id` | `validate_id_back` | Rekognition DetectText + heurística más laxa (>=2 líneas legibles). |
| POST | `/signatures/{sign_id}/evidence/face` | `sign_id` | `validate_face` | Rekognition DetectFaces: exactamente una cara, confianza >=90, ojos abiertos. |
| POST | `/signatures/{sign_id}/evidence/signature` | `sign_id` | `register_signature` | Solo valida formato/tamaño del PNG del garabato; no biométrico. |
| POST | `/signatures/{sign_id}/consent` | `sign_id` | `consent` | Registra `terms_version` y stampa `consent_given_at`. |
| POST | `/signatures/{sign_id}/otp` | `sign_id` | `request_otp` | Emite OTP nuevo, lo emailea. Idempotente como resend desde `otp`. |
| POST | `/signatures/{sign_id}/otp/verify` | `sign_id` | `verify_otp` | 5 intentos máx; al éxito llama `sign` asíncronamente si `SIGN_LAMBDA_READY=true`. |
| (sin HTTP) | `sign` | invoke async | `sign` | Worker interno; ver §7. |
| POST | `/signatures/verify` | pública | `verify` | Verifica cualquier PDF (por URL o por `sign_id`). Devuelve integridad + trust chain + contexto de la ceremony si aplica. |

Requests y respuestas concretos: leer los `handler.py` y `test.py`
colocalizados. Los tests son el contrato ejecutable.

---

## 5. Modelo de autenticación

Tres capas distintas, cada una con un mecanismo distinto y explícito:

### 5.1 M2M — `X-Service-Key` (solo `create`)

Solo `create` lo usa. Header `X-Service-Key` comparado con constant-time contra
el valor cacheado desde SSM `/cdts/{stage}/signatures/service-key`
(SecureString, KMS). Missing/incorrecto → `401`.

- El consumidor **NO** viaja por API Gateway con este header expuesto al mundo:
  llama `signatures.create` por **direct Lambda invoke** con un evento HTTP
  sintético que incluye el header (`processes/utils/signature_bridge.py`). El
  service key nunca sale de AWS.
- Un attacker que consiga el key puede abrir ceremonies falsas (crear filas en
  DB, subir PDFs al bucket) pero **no puede firmar**: la ceremonia requiere
  evidencia + OTP al email del firmante real. El worst case es DoS/basura, no
  falsificación.

### 5.2 Link-based — `sign_id` en path (todos los endpoints de ceremony)

El `sign_id` es un token urlsafe de 32 bytes (256 bits de entropía) generado por
`Signatures.new_sign_id()`. Vive en el path (`/signatures/{sign_id}/...`) y el
frontend lo tiene porque abrió el `sign_url` que llegó por email.

- Es una **capability**: quien tenga el link, firma. No hay "quién es el
  firmante": se asume implícitamente que solo el dueño del inbox lo tiene.
- El OTP al email cierra el loop: obligas al firmante a demostrar acceso a la
  cuenta que se especificó al crear la ceremony.
- Decorador: `@require_sign_id` (en `utils/auth.py`) inyecta la fila `Signatures`
  en `event["signature"]`. Missing/desconocido → `404` uniforme (no revela si
  el sign_id existe o no).

### 5.3 Zero-trust — payload como wakeup signal (webhook `signature_callback`)

`processes/signature_callback` recibe el POST del worker de firma. Pero **no
confía en lo que llega**: toma `sign_id`, ignora el resto, y relee
`Signatures.get_by_sign_id`. Detalle completo en el propio handler y en la
sección §10.

Consecuencias:

- No hay JWT, HMAC, ni shared secret en el callback.
- Un attacker con un `sign_id` random hace un no-op.
- Un attacker con un `sign_id` real no puede forzar `stage='signed'` porque
  ignoramos lo que envían.

### 5.4 Pública — verify

`/signatures/verify` no requiere auth. Acepta:

- `{"pdf_source_url": "..."}` — verifica cualquier PDF externo (cap 25 MiB).
- `{"sign_id": "..."}` — verifica el `signed.pdf` que este servicio produjo.

Devuelve integridad + validez de la firma + trust chain vs la root CA
mockeada. Si el `cert_serial` corresponde a una ceremony conocida, enriquece la
respuesta con contexto (`signer_email` enmascarado, `signed_at`, `hash_signed`).

---

## 6. Layout S3

Bucket propio del servicio: `cdts-{stage}-signatures`, definido en
`services/signatures/serverless.yml`. Configuración destacada:

- Public access block completo (nunca se sirve HTTP directo; todo pasa por
  presigned URLs con TTL corto).
- SSE-AES256 en reposo.
- CORS permisivo para PUT desde el microfrontend.
- Lifecycle: objetos bajo `transactions/*` expiran a los **30 días**. Suficiente
  para el ciclo consumo → verify → auditoría inicial; para retención larga la
  copia se archiva fuera de este bucket.

Layout por ceremony:

```text
cdts-{stage}-signatures/
└── transactions/{sign_id}/
    ├── original.pdf              ← subido por create (desde pdf_source_url)
    ├── id/
    │   ├── front.jpg  |  front.png
    │   └── back.jpg   |  back.png
    ├── face/
    │   ├── selfie.jpg |  selfie.png
    ├── signature/
    │   └── canvas.png             ← garabato del signer (PNG con alfa)
    ├── signed.pdf                 ← producido por sign
    └── evidence-package.json      ← manifiesto de auditoría (ver §11)
```

Reglas:

- Las keys las **decide `signatures`** (no el consumidor ni el firmante). Los
  presigned URLs de `upload_url` amarran la key exacta; el firmante no puede
  reescribir otro objeto.
- La extensión del ID/face la elige el consumidor; `_PROBE_MAP` en
  `services/signatures/utils/evidence.py` la resuelve al validar.
- Nada compartido con el bucket `files` de `processes` (que vive en
  `cdts-{stage}-files/processes/*`). Cada servicio tiene la potestad
  exclusiva de sus buckets. Cross-service data va por presigned URL, nunca por
  IAM directo a bucket ajeno.

---

## 7. Worker interno `sign`

Invocado asíncronamente por `verify_otp` cuando el OTP es correcto. No tiene
event HTTP (no está expuesto). Payload: `{"sign_id": "..."}`.

Pipeline (ver `services/signatures/src/handlers/sign/handler.py`):

1. Cargar la ceremony; gate `stage='signing'` (idempotencia contra reintentos
   manuales via `aws lambda invoke`).
2. Bajar el PDF original y el PNG del garabato de S3.
3. **Chequeo de integridad**: `sha256(pdf_bytes)` debe coincidir con
   `row.hash_original` guardado en `create`. Un mismatch aquí significa que
   alguien manipuló el objeto en S3 → falla `original_pdf_tampered`, no firma
   documento sustituido.
4. `issue_transaction_cert(sign_id, signer_email, signer_name)` en el mock CA
   → devuelve `(cert_pem, private_key_pem, serial_hex)`. La clave privada
   **muere con esta invocación** (nunca se persiste).
5. `stamp_drawing_on_pdf(pdf_bytes, drawing_bytes, signature_location)` estampa
   el garabato en las coordenadas que llegaron en `create`. Preserva aspect
   ratio si no se pasó `height_pct`.
6. `sign_pdf_pades_b(stamped_pdf, cert_pem, private_key_pem, invisible_loc)`
   firma en PAdES-B baseline. El campo visible del PAdES se coloca en un
   rectángulo minúsculo en la esquina para no chocar visualmente con el
   garabato ya estampado.
7. Sube `signed.pdf` a S3 y calcula `hash_signed`.
8. Marca la fila como signed vía `row.mark_signed(hash_signed, cert_serial, signed_at)`.
9. Construye el evidence package (§11) y lo sube a S3.
10. Dispara el callback HTTP al `row.callback_url` (best effort; nunca lanza
    excepción; `record_callback(sent, error)` guarda el outcome).

Todos los errores se traducen a códigos estables (`SigningError.code`) y
resultan en `row.mark_failed(code)` + rollback + return no lanzante — el
Lambda async no tiene a quién responder con 5xx.

`memorySize: 2048`, `timeout: 300`. El cost driver son los pasos 4 (cert
issuance con RSA) y 6 (PAdES signing).

---

## 8. Mock Certification Authority

Implementación en `services/signatures/utils/mock_ca.py`. Justificación
académica y explicación del contrato con las autoridades reales:
[`arquitectura_firma_digital_colombia_resumen.md`](./arquitectura_firma_digital_colombia_resumen.md).
Aquí solo lo operativo.

### 8.1 Diseño

- **Root CA**: certificado + clave privada autofirmados, guardados en SSM como
  SecureString. **Se generan una vez por stage** y se dejan quietos.
  Nunca se rotan salvo desastre.
- **Leaf cert (transaction cert)**: emitido por invocación del worker `sign`,
  con validez de 24 horas, subject `CN=<signer_name>, emailAddress=<signer_email>`,
  serial random 128 bits. Vive el tiempo que dura la Lambda. Firma sobre el PDF.
- **Trust chain**: leaf firmado por root. Al verificar, `pyhanko-certvalidator`
  valida contra la root cargada desde SSM.

### 8.2 Bootstrap del root CA (una vez por stage)

Genera el par y súbelo a SSM. Usa `openssl` (cualquier versión >= 1.1). Los
parámetros son un CA autofirmado con `basicConstraints CA:TRUE, pathlen:0` (no
puede firmar sub-CAs, solo leaves).

```bash
# Directorio temporal en tu máquina; NUNCA se comitea.
mkdir /tmp/mock-ca && cd /tmp/mock-ca

# 1) Clave privada RSA-2048 (podés usar 3072 si querés más margen).
openssl genrsa -out root.key 2048

# 2) Cert autofirmado con validez 10 años. Ajustá el subject.
openssl req -new -x509 -sha256 -days 3650 \
    -key root.key \
    -out root.crt \
    -subj "/C=CO/O=CDTS Academico/OU=Mock CA/CN=CDTS Mock Root CA {STAGE}" \
    -extensions v3_ca \
    -config <(cat <<EOF
[req]
distinguished_name = dn
[dn]
[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage         = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
EOF
)

# 3) Subilo a SSM. Cambiá {STAGE} a dev o pro.
aws ssm put-parameter \
    --name  "/cdts/{STAGE}/mock-ca/root/cert" \
    --type  SecureString \
    --value "$(cat root.crt)" \
    --description "Mock CA root certificate for signatures (v2)."

aws ssm put-parameter \
    --name  "/cdts/{STAGE}/mock-ca/root/key" \
    --type  SecureString \
    --value "$(cat root.key)" \
    --description "Mock CA root private key. Do not extract."

# 4) BORRÁ los archivos locales. La clave ya vive en KMS.
shred -u root.key root.crt   # linux
# o simplemente rm si estás en un contenedor efímero.
```

Notas importantes:

- **No** subir la clave a git ni a un secret store no-KMS. `SecureString` en
  SSM está encriptado con la KMS key `alias/aws/ssm` por default; para producción
  vale la pena rotar a una CMK propia y restringirle `kms:Decrypt`.
- **Rotación**: técnicamente romperías todas las firmas históricas al rotar el
  root (dejarían de validar). Es aceptable en dev; en pro habría que preservar
  el root viejo bajo un path distinto para que `verify` lo consulte también.
  Fuera de scope académico.

### 8.3 Bootstrap del `signatures` service key (una vez por stage)

Shared secret M2M para que `processes` (y futuros consumidores) llamen
`signatures.create`. Se genera con `openssl rand`:

```bash
# 32 bytes hex = 64 caracteres, más que suficiente para M2M.
SERVICE_KEY=$(openssl rand -hex 32)

aws ssm put-parameter \
    --name  "/cdts/{STAGE}/signatures/service-key" \
    --type  SecureString \
    --value "$SERVICE_KEY" \
    --description "M2M shared secret. Callers set X-Service-Key with this value on POST /signatures."

# NO imprimás $SERVICE_KEY en logs / historial de shell después.
unset SERVICE_KEY
```

### 8.4 Bootstrap del URL del API de `processes` (una vez por stage)

Requerido por Fase 6b para que `signature_bridge` sepa a dónde apuntar el
callback. Este valor **no** se auto-crea desde CloudFormation porque el deploy
role no tiene `ssm:PutParameter` (ver decisión en el PR de Fase 6b). Después
del primer deploy del stack `cdts-{stage}-processes` copiar el URL del output
`HttpApiUrl` y ejecutar:

```bash
# API_ID lo lee de CloudFormation. Podés hardcodear la URL si preferís.
API_ID=$(aws cloudformation describe-stacks \
    --stack-name cdts-{STAGE}-processes \
    --query "Stacks[0].Outputs[?OutputKey=='HttpApiId'].OutputValue" \
    --output text)

aws ssm put-parameter \
    --name  "/cdts/{STAGE}/processes-api/url" \
    --type  String \
    --value "https://${API_ID}.execute-api.us-east-1.amazonaws.com" \
    --description "Base URL of the processes HTTP API. Read by processes/signature_bridge to build the callback URL passed to signatures.create."
```

Si te lo saltás, `signature_bridge` abre ceremonies con `callback_url=null` y
el frontend hace polling contra `signatures.get`. El sistema funciona
end-to-end en ambos modos.

---

## 9. Parámetros SSM requeridos por `signatures`

Resumen consolidado. Todos bajo el prefijo `/cdts/{stage}/`.

| Path | Tipo | Descripción | Bootstrap |
|---|---|---|---|
| `/cdts/{stage}/db/host`, `.../port`, `.../name`, `.../user`, `.../password`, `.../schema` | Mixed | Credenciales Postgres compartidas. | Preexistente (§11 de repo-structure). |
| `/cdts/{stage}/smtp/host`, `.../port`, `.../user`, `.../password`, `.../from` | Mixed | Config SMTP para OTP. | Preexistente. |
| `/cdts/{stage}/frontend/url` | String | Base URL del microfrontend Angular. Usado por `create` para armar `sign_url`. | El pipeline del frontend lo publica. |
| `/cdts/{stage}/signatures/service-key` | SecureString | M2M para `create`. | §8.3 |
| `/cdts/{stage}/mock-ca/root/cert` | SecureString | Root CA PEM. | §8.2 |
| `/cdts/{stage}/mock-ca/root/key` | SecureString | Root CA private key PEM. | §8.2 |
| `/cdts/{stage}/processes-api/url` | String | Base URL del API de `processes` (para el callback). Opcional. | §8.4 |

Los IAM statements del stack de `signatures` (y del stack de `processes`)
permiten `ssm:GetParameter` + `kms:Decrypt` **solo** sobre los paths listados.

---

## 10. Integración con `processes`

Dos piezas del lado de `processes`:

### 10.1 `services/processes/utils/signature_bridge.py`

Se llama desde el handler `processes/advance` cuando la transición es
`documents → signature`. Renderiza el PDF de la orden CDT
(`utils/investment_order.py`), lo sube a `cdts-{stage}-files/processes/{id}/investment-order.pdf`,
genera un presigned GET (10 min TTL), y llama `signatures.create` por direct
Lambda invoke incluyendo:

- `pdf_source_url`: el presigned GET.
- `signature_location`: el `SIGNATURE_LOCATION` de `investment_order.py`.
- `signer_email`, `signer_name`: del `Users` del proceso.
- `service_caller`: `"processes"`.
- `callback_url`: viene de `_load_callback_url()` (§8.4). `null` si no está
  configurado.

Devuelve `sign_url` a `advance`, que lo mete en el response body para que el
frontend redirija al microfrontend.

Códigos de error estables (`SignatureBridgeError.code`):

- `user_missing_email`, `bank_not_found` — precondiciones.
- `service_key_unavailable` — SSM/KMS falló.
- `s3_upload_failed`, `presign_failed` — bucket problems.
- `signatures_invoke_failed` — el Lambda invoke rebotó (Lambda no existe, IAM,
  throttling).
- `signatures_create_rejected` — signatures respondió con status != 201.
- `signatures_bad_body`, `signatures_missing_field` — la respuesta llegó
  malformada; nunca debería pasar.

`advance/handler.py` mapea todos a `HandledError(502)` con el código como
`error`, para que el frontend/soporte pueda leer qué falló sin filtrar
detalles internos.

### 10.2 `services/processes/src/handlers/signature_callback/handler.py`

Público, sin auth (§5.3). Al llegar el webhook:

1. Toma `sign_id` del body.
2. `Processes.get_by_sign_id(sign_id)` → si `None`, responde 200 con
   `action=process_not_found`.
3. `Signatures.get_by_sign_id(sign_id)` → si `None`, responde 200 con
   `action=signature_not_found`.
4. Decisión según `ceremony.stage`:
   - `signed` → `proc.mark_signed_at(ceremony.signed_at)`. Idempotente: si ya
     estaba stampado, retorna `already_marked`.
   - `failed`/`expired` → log warning, no toca el proceso, retorna
     `ceremony_failed`. La UI muestra la falla y ofrece retry.
   - cualquier stage no-terminal → retorna `ceremony_pending` (defensivo; el
     worker `sign` no dispara webhook mid-flow hoy).

**Siempre 200.** Un status 4xx dispararía reintentos infinitos si el webhook
llegó a la URL equivocada; el `action` cuenta la historia al operador via logs.

### 10.3 Flujo end-to-end (happy path)

```text
Wizard step   Actor           Acción
──────────    ──────────      ──────────────────────────────────────
"documents"   frontend        POST /processes/{id}/advance
              processes       .advance() → signature_bridge:
                                * render PDF                (investment_order)
                                * upload PDF                (files bucket)
                                * presign GET               (10 min)
                                * invoke signatures.create  (X-Service-Key)
                              respuesta con sign_url
              frontend        redirige a sign_url
"signature"   signer          abre email → click en link → microfrontend
                              (repite: GET, upload_url, PUT a S3, validate_*)
                              (consent, request_otp, otp arriba por email,
                               verify_otp)
              signatures      verify_otp → invoke async sign → PAdES + evidence
                                        → POST callback_url
              processes       signature_callback
                                → mark_signed_at (idempotente)
                              return 200 action=signed_marked
              frontend        polling detecta signed_at o refresca vista
                              habilita botón "Advance a payment"
              user            click advance
              processes       advance() → Signatures.get_by_sign_id verifica
                                        stage='signed' → advance_to('payment')
```

---

## 11. Formato del evidence package

Documento JSON producido por `services/signatures/utils/evidence_package.py`.
Auto-descriptivo por diseño: un auditor debe poder leerlo sin nuestro código
fuente. Schema:

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-09-21T15:47:12+00:00",
  "sign_id": "...",
  "service_caller": "processes",
  "signer": {
    "email": "ada@example.com",
    "email_masked": "a**@example.com",
    "name": "Ada Lovelace"
  },
  "document": {
    "original_key": "transactions/{sign_id}/original.pdf",
    "signed_key":   "transactions/{sign_id}/signed.pdf",
    "hash_original": "<sha256 hex>",
    "hash_signed":   "<sha256 hex>",
    "signature_location": { "page": 1, "x_pct": 60, "y_pct": 85, "width_pct": 25 }
  },
  "evidences": {
    "uploads_state": {
      "id_front":  { "validated": true,  "key": "transactions/.../id/front.jpg"  },
      "id_back":   { "validated": true,  "key": "transactions/.../id/back.jpg"   },
      "face":      { "validated": true,  "key": "transactions/.../face/selfie.jpg" },
      "signature": { "validated": false, "key": "transactions/.../signature/canvas.png" }
    }
  },
  "consent": {
    "given_at": "2026-09-21T15:40:03+00:00",
    "terms_version": "v1"
  },
  "otp": {
    "verified_at": "2026-09-21T15:42:10+00:00",
    "max_attempts": null
  },
  "signature": {
    "algorithm": "PAdES-B baseline",
    "hash_algorithm": "sha256",
    "cert_serial": "<128-bit hex>",
    "cert_pem":    "-----BEGIN CERTIFICATE-----\n...",
    "signed_at":   "2026-09-21T15:42:12+00:00"
  },
  "timing": {
    "created_at": "2026-09-21T15:30:00+00:00",
    "expires_at": "2026-09-22T15:30:00+00:00"
  }
}
```

Reglas:

- Nunca contiene bytes de las evidencias, solo keys S3. Bajarlas es
  responsabilidad del verificador.
- Nunca contiene el OTP en claro (nunca se guarda en claro).
- Nunca contiene la clave privada del cert (murió con la Lambda `sign`).
- Es de solo escritura: `sign` lo genera una vez, no se sobrescribe.
  Segunda invocación de `sign` sobre una ceremony `signed` es no-op.

---

## 12. Endpoint `verify`

Público. Contrato mínimo:

```jsonc
// Modo A: PDF externo por URL
POST /signatures/verify
{ "pdf_source_url": "https://..." }

// Modo B: PDF nuestro por sign_id
POST /signatures/verify
{ "sign_id": "..." }
```

Uno de los dos exactamente. Response común:

```jsonc
{
  "integrity_ok": true,
  "signature_valid": true,
  "trusted_by_our_root": true,
  "signer": {                 // enmascarado
    "email_masked": "a**@example.com",
    "name": "Ada Lovelace"
  },
  "signed_at": "2026-09-21T15:42:12+00:00",
  "cert_serial": "...",
  "hash_signed": "...",
  // Presente SOLO si el cert_serial matchea una ceremony conocida.
  // No leakea sign_id completo, solo un prefijo.
  "ceremony": {
    "sign_id_prefix": "abc123",
    "service_caller": "processes",
    "created_at": "...",
    "signer_email_masked": "..."
  }
}
```

Semántica de flags:

- `integrity_ok`: el hash del cuerpo del PDF pos-firma matchea el rango firmado.
  `false` significa que alguien modificó el PDF después de firmar.
- `signature_valid`: la firma criptográfica se valida con la clave pública del
  cert.
- `trusted_by_our_root`: la cadena hasta la root cargada desde SSM valida. Un
  PDF firmado por un cert de otro CA daría `signature_valid=true` +
  `trusted_by_our_root=false`.

Cap de payload 25 MiB en modo URL. En modo `sign_id` no hay cap explícito
(el objeto lo bajamos de nuestro propio bucket).

---

## 13. Operating notes

### 13.1 Primera vez que ponés `signatures` en un stage

Orden estricto:

1. Deploy `signatures` (crea el bucket, IAM, Lambdas, HTTP API).
2. Bootstrap SSM (§8.2, §8.3). Sin la root CA el worker `sign` falla al emitir
   leaf. Sin el service key nadie puede llamar `create`.
3. Deploy `processes` (crea su stack, incluye env `SSM_PROCESSES_API_URL` y su
   IAM).
4. Bootstrap del URL del API de `processes` (§8.4). Sin esto, las ceremonies
   quedan sin callback (frontend polling funciona; solo perdés push).
5. Redeploy `processes` es opcional acá, pero recomendado para invalidar
   caches en containers warm.

Comprobaciones rápidas:

```bash
# Los tres deberían existir y tener valores no vacíos.
aws ssm get-parameter --name /cdts/dev/signatures/service-key --with-decryption --query "Parameter.Value"
aws ssm get-parameter --name /cdts/dev/mock-ca/root/cert      --with-decryption --query "Parameter.Value" | head -3
aws ssm get-parameter --name /cdts/dev/mock-ca/root/key       --with-decryption --query "Parameter.Value" | head -3
aws ssm get-parameter --name /cdts/dev/processes-api/url                        --query "Parameter.Value"
```

### 13.2 Debugging una ceremony atascada

- **Get the row**: `SELECT * FROM signatures WHERE sign_id = '<...>'` en dev.
  Todos los campos relevantes (`stage`, `otp_attempts_left`, `signature_key`,
  `hash_original`, `callback_error`, ...) están ahí.
- **Listar el S3 de esa ceremony**:
  `aws s3 ls s3://cdts-dev-signatures/transactions/<sign_id>/`
- **Logs**: cada Lambda logea en `/aws/lambda/cdts-dev-signatures-<fn>`
  (retention 14 días).
- **Sign atascado**: si `stage='signing'` sin transicionar en más de 5 min, el
  worker crashó silenciosamente. `mark_failed` lo debería haber capturado; si
  no, revisar CloudWatch. Recuperación manual:
  `aws lambda invoke --function-name cdts-dev-signatures-sign --payload '{"sign_id":"..."}' -`.
- **Callback rebota**: `SELECT callback_url, callback_sent_at, callback_error
  FROM signatures WHERE sign_id='...'`. El worker `sign` guarda el outcome.

### 13.3 Rotación del service key

```bash
NEW=$(openssl rand -hex 32)
aws ssm put-parameter --name /cdts/dev/signatures/service-key --type SecureString --value "$NEW" --overwrite
# Los containers warm de processes seguirán usando el key viejo hasta reciclar
# (~15 min de idle). Forzá un redeploy si necesitás corte inmediato:
gh workflow run deploy-dev.yml -f block=processes
unset NEW
```

Signatures **también** cachea el key en warm containers. Un `--overwrite` no
lo invalida hasta cold start; en dev es aceptable, en pro habría que
disparar redeploy también.

---

## 14. Anti-patrones

- **Meter lógica de negocio del consumidor dentro de `signatures`.** Si viste
  algo como `if service_caller == "processes": ...` en un handler de
  signatures, se rechaza en review. `signatures` no sabe qué es un proceso.
- **Compartir el bucket de `signatures` con otro servicio.** El bucket es la
  fuente de verdad de las evidencias; una escritura no autorizada rompe el
  audit trail. Cross-service = presigned URL.
- **Autenticar el callback con un shared secret.** El zero-trust reread es
  mejor que cualquier HMAC: no hay claves que rotar, no hay riesgo de leak,
  y el peor caso es un no-op por sign_id inválido.
- **Persistir el OTP en claro** en logs o en una columna de la DB. El
  handler `request_otp` deliberadamente masca el OTP en la response.
  `Signatures.otp_hash` es bcrypt; `otp_matches(code)` valida sin exponer.
- **Persistir la clave privada de un leaf cert.** El worker `sign` la usa y
  la deja morir con la invocación. Si necesitás re-firmar, emití otro leaf.
- **Extender el TTL de los presigned URLs "por comodidad".** 5 min para PUT
  y 15 min para GET son suficientes para cualquier flujo humano; extenderlos
  aumenta la ventana de leak.
- **Llamar `signatures.create` desde el frontend con el service key.** Nunca.
  El key vive solo en SSM + memoria de Lambdas. El frontend consume el
  `sign_url` que devuelve `processes/advance`; no necesita más.
- **Agregar un endpoint HTTP a `sign`.** Es un worker interno. Exponerlo
  permite firmar sin ceremony completa, saltándose la evidencia. Si se
  necesita re-firmar, se abre otra ceremony.
