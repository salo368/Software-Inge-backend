-- C11: FA1 (reutilización de documento vigente) y FE1 (formato no
-- admitido / tamaño fuera de rango).
--
-- FA1 no agrega columnas: un documento reutilizado es una fila más de
-- `documents`, con su propio s3_key_raw sintético y stage='validado'
-- desde el momento en que se crea (ver libs/orm/documents.py,
-- Documentos.register_reused). FE1 solo amplía el motivo de rechazo
-- admitido; la validación en sí vive en domain/matching.evaluar_formato,
-- no en la base de datos.

-- +migrate up

ALTER TABLE documents DROP CONSTRAINT documents_rejection_reason_check;
ALTER TABLE documents ADD CONSTRAINT documents_rejection_reason_check
    CHECK (rejection_reason IS NULL OR rejection_reason IN (
        'documento_ilegible', 'no_corresponde', 'formato_no_admitido'
    ));

-- +migrate down

ALTER TABLE documents DROP CONSTRAINT documents_rejection_reason_check;
ALTER TABLE documents ADD CONSTRAINT documents_rejection_reason_check
    CHECK (rejection_reason IS NULL OR rejection_reason IN (
        'documento_ilegible', 'no_corresponde'
    ));
