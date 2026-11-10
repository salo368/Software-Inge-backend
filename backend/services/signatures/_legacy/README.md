# `signatures` v2 — código de referencia, ya no se despliega

Todo lo que había bajo `src/` y `utils/` antes del refactor v3 (11 handlers
+ el worker `sign`, más `utils/mock_ca.py`, `evidence.py`,
`evidence_package.py`, `stamp.py`, `otp_email.py`, `emails.py`, `auth.py`)
vive acá tal cual estaba. No se borró porque todavía hace falta de
referencia mientras se reconstruye el servicio stage por stage.

**No se despliega**: `functions.js` (vía `build-functions.js`) solo
escanea `src/{handlers,scheduled,workers}` en la raíz del bloque, y
`package.patterns` en `serverless.yml` solo empaqueta `src/**`,
`libs/**` y `utils/**` (también en la raíz) — nada bajo `_legacy/`
entra en el zip ni se registra como Lambda.

La tabla `signatures` que asume este código viejo (con `sign_id`,
`signature_location`, evidencias, OTP, consent, callback, etc.) ya no
existe — fue reemplazada por el schema v3, mucho más chico
(`id`, `stage`, `doc_s3_key`, `sign_location`). Ver la migración
`20261102050000_signatures_v3_simplify.sql` y `libs/orm/signatures.py`.

Referencia de arquitectura completa de la v2 (stages, auth, bucket
layout, mock CA, worker `sign`): [`docs/signatures-v2.md`](../../../../docs/signatures-v2.md) —
también describe un estado viejo, úsalo para entender el *por qué* de
cada pieza, no como la verdad actual del sistema.
