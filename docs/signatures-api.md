# Servicio `signatures` — Manual de API (estilo Postman)

Este documento es la referencia del servicio `signatures`
(`backend/services/signatures/`): firma digital genérica de un PDF, con
validación biométrica, OTP por correo y firma PAdES-B con una CA de prueba
(mock). No conoce el dominio CDT: recibe un PDF, quién lo firma y dónde va
la firma.

Para el marco conceptual (por qué evidencia, certificado por transacción,
etc.) ver
[`arquitectura_firma_digital_colombia_resumen.md`](./arquitectura_firma_digital_colombia_resumen.md).

Los ejemplos de response son capturas reales contra `staging` (2026-11-08),
con las URLs prefirmadas recortadas.

---

## 1. Base URL

No hay servidor local: todo corre contra un stage desplegado (`dev`,
`staging` o `pro`). La URL sale del output `HttpApiUrl` del stack
`cdts-<stage>-signatures`:

```bash
aws cloudformation describe-stacks \
  --stack-name cdts-<stage>-signatures \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text
```

---

## 2. Autenticación

**Ningún endpoint usa bearer token.** La firma se identifica por su
`signature_id` (UUID), que funciona como capacidad: quien lo tiene puede
avanzar esa firma. Cada endpoint valida además el stage actual, así que no
se puede saltar pasos.

> `POST /signatures/create-signature` tampoco tiene autenticación, aunque
> solo lo usa `processes.generate_sign` (Lambda-a-Lambda).

---

## 3. Ciclo de vida de una firma

`signatures.stage` (enum `SignatureStage`):

| Stage | Se entra con | Se sale con |
|---|---|---|
| `FORM` | `create-signature` | `set-signature-form` (correo del firmante) |
| `BIOMETRICS` | `set-signature-form` | `get-required-biometrics`, cuando las 3 evidencias son válidas |
| `SIGNATURE` | `get-required-biometrics` | `set-signature-draw` (dibujo de la firma) |
| `OTP` | `set-signature-draw` | `resolve-otp` con el código correcto |
| `SIGNING` | `resolve-otp` | `sign_doc` (interna) |
| `SIGNED` | `sign_doc` | — (final) |
| `FAILED` | 3 OTP incorrectos, ventana vencida o `sign_doc` sin terminar | — (final) |

Límites (`libs/orm/signatures.py`):

| Constante | Valor | Efecto |
|---|---|---|
| `SIGNING_WINDOW` | 15 min desde `created_at` | pasado ese tiempo, los endpoints responden `410 signature_expired`, y `check_signature_timeout` marca `FAILED` la firma que no esté en `SIGNING`, `SIGNED` o `FAILED` |
| `OTP_TTL` | 2 min | vigencia de cada código |
| `MAX_OTP_TRIES` | 3 | al tercer código incorrecto la firma pasa a `FAILED` |
| `SIGNING_TIMEOUT` | 60 s | si `sign_doc` no termina, `check_signing_timeout` marca `FAILED` |

`get-signature` no responde `410` cuando la firma está en `SIGNING`,
`SIGNED` o `FAILED`, para que el frontend pueda seguir consultando el
resultado.

**Avisos al terminar** (`libs/utils/signature_notifications.py`): cuando
una firma llega a `SIGNED` o `FAILED` se invoca de forma asíncrona
`processes.signed` (ver [`processes-api.md`](./processes-api.md) §5.2). Si
es `SIGNED`, también `notify_signed`, que le manda al firmante el enlace
al PDF firmado.

---

## 4. Endpoints

Todos responden errores como `{"error": "<código>"}`. Los que reciben
`signature_id` comparten estos errores:

| status | `error` | Cuándo |
|---|---|---|
| 400 | `signature_id is required` / `invalid signature_id` | falta o no es UUID |
| 404 | `signature_not_found` | no existe |
| 410 | `signature_expired` | pasó `SIGNING_WINDOW` (ver §3) |

### 4.1 `POST /signatures/create-signature`

Abre una firma: sube el PDF al bucket de `signatures` y crea la fila en
`FORM`. También encola el aviso de vencimiento de 15 min.

**Llamada por:** `processes.generate_sign` (Lambda-a-Lambda). Ver la nota
de §2.

**Request**

- Query `sign_location`: JSON con una lista no vacía de cajas de firma.
- Query `signatory`: nombre del firmante.
- Body: los bytes del PDF.

```http
POST {{base_url}}/signatures/create-signature?sign_location=%5B%7B%22page%22%3A1%2C...%7D%5D&signatory=Usuario%20Staging%20Prueba
Content-Type: application/pdf

<bytes del PDF>
```

Formato de cada caja de `sign_location` (porcentajes desde la esquina
superior izquierda):

```json
{"page": 1, "x_pct": 8.0, "y_pct": 80.0, "width_pct": 40.0, "height_pct": 14.0}
```

| Campo | Notas |
|---|---|
| `page` | página, empezando en 1 |
| `x_pct`, `y_pct` | posición, 0–100 |
| `width_pct` | opcional (default 25) |
| `height_pct` | opcional; si falta, se deriva de la proporción del dibujo |

**Response — 200 OK**

```json
{
  "id": "6ba49b5d-8f62-4e61-affa-f51c41fd5bbe",
  "stage": "FORM",
  "doc_s3_key": "01a1b966-7272-7029-b81c-ff5198effa62.pdf",
  "signatory": "Usuario Staging Prueba",
  "sign_location": [{"page": 1, "x_pct": 8.0, "y_pct": 80.0, "width_pct": 40.0, "height_pct": 14.0}]
}
```

**Errores**

| status | `error` | Cuándo |
|---|---|---|
| 400 | `sign_location is required` | falta |
| 400 | `sign_location must be valid JSON` | no es JSON |
| 400 | `sign_location must be a non-empty list` | no es lista o está vacía |
| 400 | `signatory is required` | falta o está vacío |
| 400 | `a file is required` | body vacío |

**curl**

```bash
Q=$(python -c 'import urllib.parse as u, json; print(u.urlencode({"sign_location": json.dumps([{"page":1,"x_pct":8,"y_pct":80,"width_pct":40,"height_pct":14}]), "signatory": "Ana Gomez"}))')
curl -X POST "{{base_url}}/signatures/create-signature?$Q" \
  -H "Content-Type: application/pdf" \
  --data-binary @documento.pdf
```

---

### 4.2 `GET /signatures/get-signature`

Devuelve el estado de una firma y URLs prefirmadas (15 min) para ver el
documento. Es lo que el frontend de firma consulta para continuar.

**Request**

```http
GET {{base_url}}/signatures/get-signature?signature_id=312e7c0b-ace6-44f0-bf09-7ae729a41f30
```

**Response — 200 OK** (firma terminada)

```json
{
  "id": "312e7c0b-ace6-44f0-bf09-7ae729a41f30",
  "stage": "SIGNED",
  "sign_location": [{"page": 1, "x_pct": 8.0, "y_pct": 80.0, "width_pct": 40.0, "height_pct": 14.0}],
  "doc_url": "https://cdts-staging-signatures.s3.amazonaws.com/01a1b9ed-647d-7e0f-a9e6-e44a6eaed4af.pdf?...",
  "expires_at": "2026-11-08 07:06:45.336914+00:00",
  "raw_signed_url": "https://cdts-staging-signatures.s3.amazonaws.com/signatures/312e7c0b-ace6-44f0-bf09-7ae729a41f30/raw_signed.pdf?...",
  "signed_url": "https://cdts-staging-signatures.s3.amazonaws.com/signatures/312e7c0b-ace6-44f0-bf09-7ae729a41f30/signed.pdf?...",
  "doc_hash": "a400881dd407b608b796f5bd728617db8bc0000181a65b3caecb928bbb18f3ff",
  "signed_hash": "36538a3501b0e399521146d4d2b7e6e01ea64b25a539e58acc6a618ae8a78e9e",
  "signed_at": "2026-11-08 06:53:44.040504+00:00"
}
```

| Campo | Notas |
|---|---|
| `doc_url` | el PDF original, sin firmar |
| `expires_at` | fin de la ventana de firma (`created_at` + 15 min) |
| `raw_signed_url` | PDF con el dibujo estampado, sin página de evidencia ni firma digital; `null` hasta `SIGNED` |
| `signed_url` | PDF final: dibujo + página de evidencia + firma PAdES-B; `null` hasta `SIGNED` |
| `doc_hash` | SHA-256 del `raw_signed` (es el hash impreso en la página de evidencia) |
| `signed_hash` | SHA-256 del `signed` |

**Errores:** los comunes de §4.

---

### 4.3 `POST /signatures/set-signature-form`

Guarda el correo del firmante (adonde irá el OTP) y pasa a `BIOMETRICS`.

**Request**

```http
POST {{base_url}}/signatures/set-signature-form
Content-Type: application/json

{"signature_id": "312e7c0b-...", "email": "ana@example.com"}
```

**Response — 200 OK**

```json
{"id": "312e7c0b-...", "stage": "BIOMETRICS", "email": "ana@example.com"}
```

**Errores** (además de los comunes)

| status | `error` | Cuándo |
|---|---|---|
| 400 | `invalid_email` | email vacío o con formato inválido |
| 409 | `signature_not_in_form_stage` | la firma no está en `FORM` |

---

### 4.4 `POST /signatures/upload-biometrics`

Devuelve una URL `PUT` prefirmada (15 min) para subir una de las tres
evidencias. Después se sube la imagen con `Content-Type` igual al pedido y
se valida con §4.5.

**Request**

```http
POST {{base_url}}/signatures/upload-biometrics
Content-Type: application/json

{"signature_id": "312e7c0b-...", "biometric_type": "ID_FRONT", "content_type": "image/png"}
```

| Campo | Reglas |
|---|---|
| `biometric_type` | `ID_FRONT`, `ID_BACK` o `FACE` |
| `content_type` | `image/jpeg` (default) o `image/png` |

**Response — 200 OK**

```json
{
  "upload_url": "https://cdts-staging-signatures.s3.amazonaws.com/signatures/312e7c0b-.../id_front.png?...",
  "key": "signatures/312e7c0b-.../id_front.png",
  "content_type": "image/png",
  "expires_in": 900
}
```

**curl — subir la imagen**

```bash
curl -X PUT "$UPLOAD_URL" -H "Content-Type: image/png" --data-binary @cedula_frente.png
```

**Errores** (además de los comunes)

| status | `error` | Cuándo |
|---|---|---|
| 400 | `biometric_type must be one of ['FACE', 'ID_BACK', 'ID_FRONT']` | tipo inválido |
| 400 | `content_type must be one of ['image/jpeg', 'image/png']` | formato inválido |
| 409 | `signature_not_in_biometrics_stage` | la firma no está en `BIOMETRICS` |

---

### 4.5 `POST /signatures/set-biometrics`

Analiza con Amazon Rekognition una evidencia ya subida y, si es válida, la
guarda en la firma.

**Request**

```http
POST {{base_url}}/signatures/set-biometrics
Content-Type: application/json

{"signature_id": "312e7c0b-...", "biometric_type": "ID_FRONT", "s3_key": "signatures/312e7c0b-.../id_front.png"}
```

`s3_key` es el `key` que devolvió `upload-biometrics`; debe empezar por
`signatures/<signature_id>/`.

**Response — 200 OK**

```json
{"is_valid": true, "reason": "ok"}
```

Una evidencia rechazada también responde 200, con `is_valid: false` y el
motivo; se puede volver a subir y validar.

| `reason` | Tipo | Significado |
|---|---|---|
| `ok` | todos | válida |
| `evidence_missing` | todos | no hay objeto en esa `s3_key` |
| `evidence_too_large` | todos | más de 5 MiB (límite de Rekognition) |
| `too_few_legible_lines` | `ID_FRONT`, `ID_BACK` | menos de 3 (frente) o 2 (reverso) líneas legibles |
| `no_id_number_detected` | `ID_FRONT` | menos de 6 dígitos en total |
| `no_face_detected` / `multiple_faces` | `FACE` | debe haber exactamente un rostro |
| `low_confidence` | `FACE` | confianza del rostro < 90 % |
| `eyes_closed` | `FACE` | ojos cerrados o confianza < 80 % |

**Errores** (además de los comunes)

| status | `error` | Cuándo |
|---|---|---|
| 400 | `biometric_type must be one of ['FACE', 'ID_BACK', 'ID_FRONT']` | tipo inválido |
| 400 | `s3_key is required` | falta |
| 400 | `s3_key does not belong to this signature` | la ruta no es de esta firma |
| 409 | `signature_not_in_biometrics_stage` | la firma no está en `BIOMETRICS` |
| 409 | `biometric_already_set` | esa evidencia ya se validó |

---

### 4.6 `GET /signatures/get-required-biometrics`

Dice qué evidencias ya están validadas. **Efecto lateral:** si la firma
está en `BIOMETRICS` y las tres están en `true`, la pasa a `SIGNATURE`.

**Request**

```http
GET {{base_url}}/signatures/get-required-biometrics?signature_id=312e7c0b-...
```

**Response — 200 OK**

```json
{"ID_FRONT": true, "ID_BACK": true, "FACE": true}
```

**Errores:** los comunes de §4.

---

### 4.7 `POST /signatures/set-signature-draw`

Recibe la imagen de la firma dibujada (bytes crudos en el body) y pasa a
`OTP`. Se guarda en `signatures/<id>/draw.bin`.

**Request**

```http
POST {{base_url}}/signatures/set-signature-draw?signature_id=312e7c0b-...
Content-Type: application/octet-stream

<bytes de la imagen>
```

El endpoint solo valida el tamaño (entre 100 B y 2 MB), pero `sign_doc`
estampa la imagen en el PDF, así que debe ser un PNG (o JPEG). Si no es una
imagen, la firma falla en `SIGNING` y termina en `FAILED`.

**Response — 200 OK**

```json
{"id": "312e7c0b-...", "stage": "OTP", "draw_s3_key": "signatures/312e7c0b-.../draw.bin"}
```

**Errores** (además de los comunes)

| status | `error` | Cuándo |
|---|---|---|
| 422 | `draw_invalid_empty` | menos de 100 bytes |
| 413 | `draw_invalid_too_large` | más de 2 MB |
| 409 | `signature_not_in_signature_stage` | la firma no está en `SIGNATURE` |

**curl**

```bash
curl -X POST "{{base_url}}/signatures/set-signature-draw?signature_id=$SIGNATURE_ID" \
  -H "Content-Type: application/octet-stream" --data-binary @firma.png
```

---

### 4.8 `POST /signatures/set-otp`

Genera un código de 6 dígitos (vigencia 2 min), lo envía al correo del
firmante y reinicia los intentos a 0. Sirve también para reenviar.

**Request**

```http
POST {{base_url}}/signatures/set-otp
Content-Type: application/json

{"signature_id": "312e7c0b-..."}
```

**Response — 200 OK**

```json
{
  "id": "312e7c0b-...",
  "stage": "OTP",
  "email_sent": true,
  "expires_at": "2026-11-08 06:54:52.678010+00:00"
}
```

`email_sent: false` significa que el servidor de correo rechazó el envío;
el código existe igual, pero el firmante no lo recibió.

**Errores** (además de los comunes)

| status | `error` | Cuándo |
|---|---|---|
| 409 | `signature_not_in_otp_stage` | la firma no está en `OTP` |

---

### 4.9 `POST /signatures/resolve-otp`

Verifica el código. Si es correcto, pasa a `SIGNING` e invoca `sign_doc` de
forma asíncrona; el frontend debe consultar `get-signature` hasta ver
`SIGNED` (toma unos segundos). Guarda IP, user agent e idioma de la
petición para la página de evidencia.

**Request**

```http
POST {{base_url}}/signatures/resolve-otp
Content-Type: application/json

{"signature_id": "312e7c0b-...", "code": "496730"}
```

**Response — 200 OK**

```json
{"id": "312e7c0b-...", "stage": "SIGNING"}
```

**Errores** (además de los comunes)

| status | body | Cuándo |
|---|---|---|
| 400 | `{"error": "code is required"}` | falta `code` |
| 400 | `{"error": "invalid_code_format"}` | no son 6 dígitos |
| 409 | `{"error": "signature_not_in_otp_stage"}` | la firma no está en `OTP` |
| 409 | `{"error": "otp_not_requested"}` | no se ha llamado `set-otp` |
| 401 | `{"error": "otp_expired"}` | pasaron más de 2 min; pedir otro con `set-otp` |
| 401 | `{"error": "otp_invalid", "attempts_left": 2}` | código incorrecto |
| 429 | `{"error": "otp_max_attempts"}` | tercer código incorrecto; la firma pasa a `FAILED` |
| 502 | `{"error": "sign_doc_unavailable"}` | AWS rechazó la invocación de `sign_doc` |

---

## 5. Lambdas internas

| Lambda | Disparo | Qué hace |
|---|---|---|
| `sign_doc` (`handlers/`) | `resolve-otp`, asíncrona | ver abajo |
| `notify_signed` (`handlers/`) | al quedar `SIGNED`, asíncrona | envía al firmante un correo con el enlace (prefirmado) al PDF firmado |
| `check_signature_timeout` (`workers/`, SQS) | 15 min después de `create-signature` | marca `FAILED` si la firma no está en `SIGNING`, `SIGNED` ni `FAILED` |
| `check_signing_timeout` (`workers/`, SQS) | 60 s después de `resolve-otp` | marca `FAILED` si la firma sigue en `SIGNING` |

**`sign_doc`, paso a paso:**

1. Descarga el PDF, el dibujo y las tres evidencias.
2. Estampa el dibujo en cada caja de `sign_location` → `raw_signed.pdf`.
   Su SHA-256 es el `doc_hash`.
3. Emite un certificado de transacción (RSA-2048, 1 h) firmado por la CA
   de prueba.
4. Agrega una página de evidencia: firmante, correo, fecha, fotos de la
   cédula, selfie, dibujo, serial del certificado, `doc_hash` y los datos
   de la petición.
5. Firma el resultado con PAdES-B → `signed.pdf` (su SHA-256 es el
   `signed_hash`).
6. Sube los dos PDF, marca `SIGNED` y dispara los avisos de §3.

Si algo falla, `sign_doc` no marca `FAILED`: deja la firma en `SIGNING` y
`check_signing_timeout` la cierra a los 60 s.

---

## 6. Bucket y configuración

Bucket `cdts-<stage>-signatures` (propio del servicio; no comparte nada con
el de `files`):

```
<uuid7>.pdf                       ← PDF original (create-signature)
signatures/<signature_id>/
├── id_front.{jpg,png}            ← evidencias (upload-biometrics)
├── id_back.{jpg,png}
├── face.{jpg,png}
├── draw.bin                      ← dibujo de la firma
├── raw_signed.pdf                ← PDF con el dibujo estampado
└── signed.pdf                    ← PDF final firmado
```

Parámetros SSM que lee el servicio:

| Parámetro | Uso |
|---|---|
| `/cdts/<stage>/db` | conexión a la base |
| `/cdts/<stage>/smtp` | envío de correos (OTP y firma completada) |
| `/cdts/<stage>/mock-ca/root/cert-pem` y `.../private-key-pem` | raíz de la CA de prueba (SecureString) |

Los dos de la CA se crean una vez por stage con
`scripts/bootstrap-signatures-v2.sh`. Ese script también crea
`signatures/service-key`, `processes-api/url` y `signatures/debug-otp-key`,
que el código actual ya no usa.
