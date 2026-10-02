-- C11 "Capturar y validar documentación de soporte" (flujo básico).
-- Un `documents` por tipo de documento por proceso; `document_events` es
-- la bitácora de auditoría append-only (Q22R01) -- nunca se actualiza una
-- fila existente, solo se insertan hechos nuevos.
--
-- FE2 (vencido) y FA1/FA2 (reutilización, documentación corporativa) son
-- slices siguientes -- no se agregan columnas que el flujo básico no
-- ejercita todavía (ver docs del caso de uso).

-- +migrate up

CREATE TABLE documents (
    id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    process_id        UUID          NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    document_type     VARCHAR(50)   NOT NULL,
    stage             VARCHAR(20)   NOT NULL DEFAULT 'pendiente',
    s3_key_raw        TEXT          NOT NULL UNIQUE,
    s3_key_evidence   TEXT,
    hash_sha256       VARCHAR(64),
    rejection_reason  VARCHAR(50),
    uploaded_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    validated_at      TIMESTAMPTZ,
    CONSTRAINT documents_stage_check
        CHECK (stage IN ('pendiente', 'validando', 'validado', 'rechazado')),
    CONSTRAINT documents_rejection_reason_check
        CHECK (rejection_reason IS NULL OR rejection_reason IN ('documento_ilegible', 'no_corresponde'))
);

CREATE INDEX documents_process_id_idx ON documents (process_id, uploaded_at DESC);

CREATE TABLE document_events (
    id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID          NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    event_type   VARCHAR(50)   NOT NULL,
    actor        VARCHAR(100)  NOT NULL,
    result       VARCHAR(50),
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX document_events_document_id_idx ON document_events (document_id, created_at);

-- +migrate down

DROP TABLE document_events;
DROP TABLE documents;
