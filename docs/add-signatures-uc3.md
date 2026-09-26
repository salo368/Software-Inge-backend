# ADD — `services/signatures` para el Caso de Uso 3.0 (Originación de CDT)

Este documento aplica retroactiva y prospectivamente el método ADD
(Attribute-Driven Design, SEI) al servicio `signatures/` — árbol de utilidad,
drivers, decisiones ya tomadas y decisiones nuevas de esta iteración, con
trazabilidad explícita hacia los RF/RNF capturados en
`PICA.HT1.Requerimientos del Proyecto - MejorCDT.docx` (Tablas 10-13).

No repite lo operativo — para endpoints, ciclo de vida, auth y bootstrap ver
[`signatures-v2.md`](./signatures-v2.md). Este documento es sobre **por qué**,
no **cómo**.

**Vistas UML** (notación 4+1 / Kruchten): las vistas de Despliegue y de
Código de este slice están en
[`add-signatures-uc3-vistas.drawio`](./add-signatures-uc3-vistas.drawio)
(dos páginas en un mismo archivo, abrir con [draw.io / diagrams.net](https://app.diagrams.net)).
La vista de despliegue traza 1:1 con la topología de §2 de `signatures-v2.md`
y con el split de retención de §5.1 de este documento; la vista de código
traza 1:1 con el layout real de `backend/services/signatures/` (paquetes
`handlers`, `utils`, `libs.core`, `libs.orm`).

---

## 1. Contexto y alcance

Caso de Uso 3.0 "Originación de CDT", pasos 6 ("firmar electrónicamente") y
8-9 ("transmitir a la entidad financiera"). Tabla 11 de PICA.HT1 identifica
ambos como ASR (Architecturally Significant Requirements) del proyecto
completo; este documento cubre solo el slice implementado en
`backend/services/signatures/` (el worker `sign` + los 12 handlers HTTP de la
ceremonia) y su integración con `processes` (bridge + callback).

---

## 2. Drivers y restricciones aplicables

De Tabla 13 (PICA.HT1), restricciones que SÍ aplican a este slice tal como
está implementado hoy (AWS Lambda + S3, no Docker/Azure-VM):

- **TLS 1.2+ en tránsito.** API Gateway HTTP API v2 fuerza TLS 1.2 por
  defecto en todos los endpoints; no hay downgrade posible a nivel de
  configuración de este servicio.
- **Retención regulatoria de evidencia.** El número exacto (10 años) viene
  de Tabla 13 de PICA.HT1, no de ningún documento previo de este repo —
  confirmado por búsqueda: `docs/arquitectura_firma_digital_colombia_resumen.md`
  no cita ningún período de retención específico. Se toma la cifra de
  PICA.HT1 como la fuente de verdad del requisito.
- **Metodología Caso de Uso 3.0.** Este documento y el árbol de utilidad de
  la sección 3 son la forma en que ese requisito metodológico se satisface
  para este slice.

Restricción de Tabla 13 que **NO aplica** y no se revierte aquí: despliegue
en contenedores Docker sobre VMs serie B de Azure. La implementación real
diverge deliberadamente hacia AWS Lambda serverless — divergencia ya
detectada y documentada en revisiones anteriores de este proyecto. Forzar la
migración a Docker/Azure contradiría el resto de la arquitectura del backend
(11+ servicios Lambda ya desplegados) sin ningún beneficio de calidad
correspondiente; se deja fuera de alcance.

---

## 3. Árbol de utilidad

Formato: atributo → escenario concreto (fuente: Tabla 12 PICA.HT1, salvo que
se indique otra) → prioridad/dificultad (Alta/Media/Baja) → estado → evidencia.

### 3.1 Confidencialidad

| Escenario | Prioridad/Dificultad | Estado | Evidencia |
|---|---|---|---|
| Datos en tránsito cifrados (TLS 1.2+) | (A, B) | **Satisfecho** | API Gateway HTTP API v2, TLS forzado por plataforma; sin config propia que lo pueda bajar. |
| Datos en reposo cifrados (AES-256) | (A, B) | **Satisfecho, con matiz** | `serverless.yml`: `BucketEncryption: SSEAlgorithm: AES256` (SSE-S3). Tabla 12 pide "AES-256-GCM" explícito; SSE-S3 usa AES-256 pero AWS no documenta públicamente el modo de cifrado exacto como GCM. Garantía práctica equivalente, **sin confirmación formal de que el modo sea GCM** — brecha declarada en §6. |
| Clave privada del cert de firma nunca persiste | (A, A) — decisión propia, no en Tabla 12 pero central para no-repudio | **Satisfecho** | `sign/handler.py`: `private_key_pem` vive solo en el scope local de la invocación Lambda; muere con el proceso. Ver §4.3. |
| OTP nunca se guarda en claro | (A, B) | **Satisfecho** | `Signatures.otp_hash` es bcrypt; `docs/signatures-v2.md` §14 anti-patrones lo declara explícitamente prohibido. |

### 3.2 Disponibilidad

| Escenario | Prioridad/Dificultad | Estado | Evidencia |
|---|---|---|---|
| El firmante puede reanudar la ceremonia en cualquier momento mientras no sea terminal | (A, B) | **Satisfecho** | `docs/signatures-v2.md` §3: "El firmante puede reabrir el link cuantas veces quiera"; `get` es idempotente y stateless respecto al polling. |
| El callback a `processes` no bloquea la firma si falla | (M, B) | **Satisfecho** | `sign/handler.py::_fire_callback` — best effort, nunca lanza; `record_callback` guarda el outcome para diagnóstico sin afectar `row.stage`. |

### 3.3 Rendimiento

| Escenario | Prioridad/Dificultad | Estado | Evidencia |
|---|---|---|---|
| P95 ≤ 2s bajo 500 sesiones concurrentes | (A, A) | **Parcialmente verificado** | `backend/tests/services/signatures/utils/test_signing_pipeline_rnf.py::test_p95_latency_under_budget`. Medido en esta máquina de desarrollo (Windows, Python 3.12, 8 threads, N=30): **P95 = 1.523s** (mediana 1.165s, min 0.597s, max 1.559s), contra el presupuesto de 2.0s. **Lo que esto NO prueba**: que AWS Lambda sostiene 500 invocaciones concurrentes reales — eso es autoscaling de la plataforma, no del código, y requiere un load-test contra `dev` desplegado (herramienta tipo k6/locust). Brecha declarada en §6. |

### 3.4 Tolerancia a fallos

| Escenario | Prioridad/Dificultad | Estado | Evidencia |
|---|---|---|---|
| Recuperación/detección de fallo ≤ 5s | (A, B) | **Satisfecho, con reinterpretación explícita** | `test_signing_pipeline_rnf.py::test_injected_failure_surfaces_quickly`. Lambda no tiene proceso persistente que "recuperar"; el escenario se reinterpreta como *latencia de detección* — tiempo entre el fallo inyectado y `SigningError` levantado. Medido: sub-segundo (guardrail de regresión, no cota de estrés real). |
| Integridad ante manipulación del PDF fuente | (A, M) — no está en Tabla 12 pero es un ASR real encontrado en el código | **Satisfecho** | `sign/handler.py` paso 3: `sha256(pdf_bytes)` vs `row.hash_original`; mismatch → `SigningError("original_pdf_tampered")`, no firma documento sustituido. |
| Reintentos manuales no duplican efectos (idempotencia) | (A, M) | **Satisfecho** | `sign/handler.py::handler` gatea en `row.stage in ("signed","failed","expired")` antes de reprocesar; ver docstring "Idempotence". |

### 3.5 Modificabilidad

| Escenario | Prioridad/Dificultad | Estado | Evidencia |
|---|---|---|---|
| Agregar un nuevo consumidor de `signatures` sin tocar su lógica interna | (M, B) | **Satisfecho** | §1 de `signatures-v2.md`: servicio agnóstico al dominio, auth M2M genérica por `X-Service-Key`, sin `if service_caller == "..."` en el código (anti-patrón explícitamente prohibido). |
| Cada handler es testeable en aislamiento (TDD) | (A, B) | **Satisfecho** | 12/12 handlers con `test.py` colocalizado, mínimo 3 casos; `integration.py` opcional gateado por `--integration`. |

---

## 4. Decisiones de arquitectura ya tomadas (retroactivo)

Estas decisiones existían antes de esta iteración; se documentan aquí por
primera vez con su trazabilidad a atributos de calidad, que es exactamente
el vacío que esta revisión ADD vino a cerrar.

1. **Máquina de estados explícita** (`created → identity → consent → otp →
   signing → signed`, con `failed`/`expired` como terminales) — satisface
   Disponibilidad (§3.2) y Tolerancia a fallos (§3.4): cada transición tiene
   una única fuente autorizada y `ensure_stage_allows` la protege.
2. **Callback zero-trust** (`processes/signature_callback` ignora el payload
   y relee el estado por `sign_id`) — satisface Confidencialidad (§3.1) sin
   necesitar HMAC/shared secret rotable.
3. **Cert efímero, clave privada nunca persistida** — satisface
   Confidencialidad (§3.1): el peor caso de una Lambda comprometida en pleno
   vuelo es una sola firma, no la capacidad de firmar indefinidamente.
4. **Tres capas de auth distintas y explícitas** (M2M, capability `sign_id`,
   zero-trust) en vez de un único mecanismo genérico — satisface
   Confidencialidad y Modificabilidad (§3.5): cada superficie tiene el
   mecanismo mínimo necesario, no una autenticación uniforme sobrecargada.
5. **TDD por handler con `test.py` obligatorio** — satisface Modificabilidad
   (§3.5): ningún cambio de lógica se merge sin su prueba, per convención de
   `CONTRIBUTING.md` y `docs/repo-structure.md`.

---

## 5. Decisiones nuevas de esta iteración

### 5.1 Split de prefijo S3 (`transactions/` vs `evidence-archive/`)

Antes: un solo prefijo `transactions/{sign_id}/`, expiración uniforme a 30
días para todo (original, evidencia biométrica, PDF firmado, manifiesto).
Esto satisfacía privacidad/minimización pero **violaba** la restricción
regulatoria de retención de 10 años de Tabla 13 — sin mecanismo de archivado,
solo un comentario reconociendo el gap.

Ahora: `sign/handler.py` escribe el PDF firmado y el manifiesto de auditoría
bajo un prefijo nuevo, `evidence-archive/{sign_id}/`, con su propia regla de
lifecycle (`Transitions` a `GLACIER_IR` a los 30 días, `ExpirationInDays:
3650`). El prefijo `transactions/` (evidencia biométrica + original) no
cambia de comportamiento.

**Por qué prefijo y no tag S3**: la evidencia biométrica se sube por PUT
presignado directo desde el navegador (`upload_url`); taguearla habría
requerido coordinar un cambio en el frontend (`Software-Inge-frontend`,
repo aparte) para enviar `x-amz-tagging` en cada PUT. El split por prefijo
solo toca las dos escrituras que el worker `sign` ya controla del lado del
servidor — cero coordinación cross-repo, cero cambio de IAM (mismo bucket).

**Por qué GLACIER_IR y no GLACIER/DEEP_ARCHIVE**: `verify` y `get` sirven
`signed_pdf_url` bajo demanda, en cualquier momento dentro de los 10 años.
GLACIER/DEEP_ARCHIVE requieren un `RestoreObject` de horas antes de poder
leer — habría roto ambos endpoints después del día 30. GLACIER_IR da el
mismo costo de archivado con lectura en milisegundos.

### 5.2 Benchmark sintético de latencia del pipeline de firma

Nuevo: `backend/tests/services/signatures/utils/test_signing_pipeline_rnf.py`,
marcado `rnf` en `pytest.ini`. Mide P95 de los tres pasos CPU-bound del
worker `sign` (emisión de cert + estampado + firma PAdES-B) bajo concurrencia
de threads local. Ver §3.3 para los resultados medidos y su alcance
explícitamente limitado.

---

## 6. Brechas conocidas que quedan abiertas

Declaradas explícitamente, no ocultas:

1. **Load-test real contra infraestructura desplegada.** El benchmark de
   §3.3/§5.2 acota la latencia de una invocación bajo contención local; no
   prueba que AWS Lambda sostiene 500 sesiones concurrentes reales. Requiere
   una herramienta tipo k6/locust contra el stage `dev`, fuera de alcance de
   este slice.
2. **AES-256-GCM (Tabla 12) vs SSE-S3 `AES256` (implementación real).** No
   hay evidencia de que el modo de cifrado interno de SSE-S3 sea
   específicamente GCM — AWS no lo documenta públicamente. La garantía
   práctica (confidencialidad en reposo con AES-256) se considera
   equivalente para los fines de este proyecto académico, pero la
   equivalencia exacta de modo de cifrado no está confirmada.
3. **"500 sesiones concurrentes" es ambiguo sin una definición operacional
   explícita** (¿500 ceremonias abiertas simultáneamente a lo largo de su
   ciclo de vida humano-paced, o 500 invocaciones concurrentes de un mismo
   endpoint en un instante?). Este documento asume la segunda lectura (la
   que efectivamente estresa el código), pero no hay confirmación de que sea
   la lectura que el Caso de Uso 3.0 original quiso decir.

---

## 7. Flujos Use-Case 3.0 — slice "Firmar electrónicamente" (UC3, paso 6)

**Nota de trazabilidad honesta**: `PICA.HT1.docx` menciona "Use-Case 3.0" una
sola vez (Tabla 13, como restricción metodológica — *"construir el sistema por
slices verificables con pruebas automatizadas"*), sin plantilla de flujos. No
existe en ningún documento del proyecto una especificación de flujo principal
/ alternativo / error al estilo Jacobson. Los flujos que siguen **se
construyen aquí por primera vez**, con la plantilla estándar de slice
(flujo principal → extensión alterna → extensión de error), anclados 1:1 al
código real — no son una cita de un documento preexistente.

### 7.1 Flujo principal (resumen; detalle completo en `signatures-v2.md` §7)

1. `processes.advance` invoca `signatures.create` (M2M) con el PDF renderizado.
2. El firmante abre `sign_url`, sube evidencia biométrica (ID + rostro) y su
   firma dibujada; el sistema valida cada evidencia automáticamente.
3. El firmante acepta el consentimiento.
4. El sistema emite un OTP al correo del firmante (`request_otp`).
5. El firmante ingresa el OTP correcto (`verify_otp`).
6. El worker `sign` emite un certificado efímero, estampa la firma, aplica
   PAdES-B y genera el paquete de evidencia.
7. `processes.signature_callback` recibe la notificación (zero-trust) y
   marca el proceso como firmado.

### 7.2 Flujo alternativo — 6a. Reenvío de OTP

**Disparador**: el firmante no recibe el correo o el código expiró.

| Paso | Actor/Sistema | Acción |
|---|---|---|
| 6a.1 | Firmante | Pulsa "reenviar código" en el microfrontend, estando en `stage='otp'`. |
| 6a.2 | Sistema | `request_otp` acepta el reintento porque `stage in ('consent', 'otp')` — el segundo caso es explícitamente el botón de reenvío. |
| 6a.3 | Sistema | `Signatures.issue_otp()` regenera el hash y **resetea el contador de intentos**, invalidando implícitamente el código anterior (no hay dos OTP válidos a la vez). |
| 6a.4 | Sistema | Envía el nuevo correo; retorna 200 sin exponer el código en claro. |
| — | — | Reincorpora al flujo principal en el paso 5, sin reiniciar la ceremonia ni perder la evidencia ya validada. |

Evidencia: `src/handlers/request_otp/handler.py` líneas 1-11 (docstring
"Flow", paso 2).

### 7.3 Flujo de error — 6b. Intentos de OTP agotados (entrada del actor)

**Disparador**: el firmante ingresa un código incorrecto 5 veces.

| Paso | Actor/Sistema | Acción |
|---|---|---|
| 6b.1 | Firmante | Ingresa un código de 6 dígitos que no coincide con el hash almacenado. |
| 6b.2 | Sistema | `row.otp_matches(code)` es `False` → `register_failed_attempt()` decrementa el contador. |
| 6b.3 | Sistema | Si `attempts_left > 0`: responde `401 otp_invalid` con `attempts_left` restante — el firmante puede reintentar (vuelve a 6b.1). |
| 6b.4 | Sistema | Si `attempts_left <= 0`: `row.mark_failed("otp_max_attempts")` → la ceremonia queda **terminal** (`stage='failed'`); responde `429`. |
| 6b.5 | Firmante/Proceso | La ceremonia no se puede reabrir a sí misma (terminal). El proceso original debe reabrir una **nueva** ceremonia vía `processes/advance` ("reopen" logic, §10.4 de `signatures-v2.md`), preservando el resto del wizard. |

Evidencia: `src/handlers/verify_otp/handler.py` líneas 96-115 (chequeo de
intentos agotados, antes y después de la verificación).

### 7.4 Flujo de error — 6c. Falla del proveedor interno de firma (RNF, no de entrada del actor)

**Disparador**: distinto en naturaleza al 6b — no es un error del firmante,
sino la materialización directa del escenario de calidad ya documentado en
Tabla 12 de PICA.HT1, Escenario 2: *"Proveedor externo (identidad, firma
electrónica o pagos) deja de responder → el sistema debe... marcar el
proveedor como indisponible sin perder los datos ya capturados, detectado en
máximo 5 segundos, incluidos los reintentos."*

| Paso | Actor/Sistema | Acción |
|---|---|---|
| 6c.1 | Sistema | Tras un OTP correcto, `verify_otp` intenta invocar de forma asíncrona el worker interno `sign` (`invoke_async`). |
| 6c.2 | AWS | El invoke es rechazado (throttling, IAM, Lambda no desplegada) → `LambdaInvokeError`. |
| 6c.3 | Sistema | `verify_otp` **ya avanzó** `row.start_signing()` antes de invocar — los datos capturados (evidencia, consentimiento, OTP verificado) **no se pierden**. Responde `502 sign_lambda_unavailable`. |
| 6c.4 | Operador/Sistema | Puede reintentar manualmente (`aws lambda invoke --function-name cdts-{stage}-signatures-sign`), sin que el firmante repita ningún paso ya completado. |

Evidencia: `src/handlers/verify_otp/handler.py` líneas 117-136 (orden
deliberado: avanzar el estado ANTES de invocar, para que un fallo del invoke
no tire la evidencia ya capturada).

**Nota**: 6c no cumple literalmente el bound de "detectado en máximo 5
segundos" porque no hay una prueba automatizada que lo mida en este slice —
mismo gap ya declarado en §6.1 sobre el benchmark sintético (mide latencia de
firma, no latencia de detección de fallo del invoke). Queda como brecha
abierta, no como verificado.

---

## 8. Siguiente slice propuesto: UC3 pasos 7-9 (pago + transmisión a la entidad financiera)

**Hallazgo que motiva esta propuesta**: `backend/services/processes/src/handlers/advance/handler.py`
línea 25 dice textualmente: *"payment: mocked. Any advance call moves it to
done."* No existe pasarela de pago real, ni integración con ninguna entidad
financiera, ni generación de radicado — el paso "payment" es un stub que
avanza el proceso sin hacer nada.

**Por qué es el siguiente slice, no una hipótesis**:

- Es la continuación inmediata de UC3 después de "firmar electrónicamente"
  (paso 6, ya resuelto por este mismo servicio) — los pasos 7-9 son:
  "pagar" → "transmitir a la entidad financiera y recibir radicado" →
  "recibir aprobación/condiciones" → "recibir/verificar/publicar certificado"
  (Tabla 10, Módulo 3, PICA.HT1).
- Tabla 11 de PICA.HT1 ya seleccionó explícitamente **"UC3-pasos8-9
  transmitir a entidad financiera"** como ASR de alta prioridad arquitectónica
  — no es una elección mía, es un requisito ya señalado por el propio
  documento de requerimientos y todavía no atendido.
- Es verificable en código, no una suposición: el stub está confirmado en la
  línea citada arriba.

**Drivers/ASR esperables para este slice** (a validar cuando se aborde, no
comprometidos aquí):

- **Confiabilidad transaccional**: a diferencia de `signatures` (que puede
  reintentar libremente porque no mueve dinero), este slice sí mueve dinero
  real hacia una entidad financiera — necesita idempotencia estricta a nivel
  de solicitud de pago (evitar doble cobro en reintentos) y un estado
  intermedio explícito tipo `payment_pending` antes de `done`, en vez del
  salto directo actual.
- **Integración con proveedor externo**: la entidad financiera es un
  proveedor externo real (o su mock análogo al mock CA de `signatures`) —
  aplica el mismo escenario RNF de Tabla 12 Escenario 2 (proveedor cae,
  detectar en ≤5s, no perder datos) que ya se demostró resoluble en
  `signatures` §7.4 arriba.
- **Evidencia/auditoría del radicado**: mismo patrón de retención regulatoria
  ya resuelto en `signatures` (split de prefijo S3 + `GLACIER_IR`, §5.1) es
  directamente reutilizable si el radicado necesita retención de largo plazo.

**Alcance aproximado** (para dimensionar, no para implementar en esta
pasada): nuevo servicio `backend/services/payments/` (o un stage
`processes.stage='payment'` con su propio slice de handlers), con
`domain/` desde el día uno (a diferencia de los 6 servicios existentes,
ninguno lo tiene) para no repetir el mismo hallazgo de Transaction Script que
esta auditoría encontró en todo el backend.
