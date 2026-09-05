-- CDTS - Schema inicial (idempotente, se puede re-ejecutar)

-- Funcion auxiliar para auto-actualizar updated_at en cada UPDATE
CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ==============================================================
-- users
-- ==============================================================
CREATE TABLE IF NOT EXISTS public.users (
    id            BIGSERIAL    PRIMARY KEY,
    username      VARCHAR(50)  UNIQUE NOT NULL,
    name          VARCHAR(200) NOT NULL,
    password_hash TEXT         NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_users_updated_at ON public.users;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ==============================================================
-- cdts
-- ==============================================================
CREATE TABLE IF NOT EXISTS public.cdts (
    id            BIGSERIAL      PRIMARY KEY,
    user_id       BIGINT         NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    stage         VARCHAR(30)    NOT NULL,
    bank          VARCHAR(50)    NULL,
    rate          NUMERIC(5,2)   NOT NULL,
    amount        NUMERIC(15,2)  NOT NULL,
    term          INTEGER        NOT NULL,
    signature_url TEXT           NULL,
    opened_at     TIMESTAMPTZ    NOT NULL,
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_cdts_updated_at ON public.cdts;
CREATE TRIGGER trg_cdts_updated_at BEFORE UPDATE ON public.cdts
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX IF NOT EXISTS idx_cdts_user_id ON public.cdts(user_id);
ALTER TABLE public.cdts ADD COLUMN IF NOT EXISTS bank VARCHAR(50) NULL;

-- ==============================================================
-- files
-- ==============================================================
CREATE TABLE IF NOT EXISTS public.files (
    id         BIGSERIAL    PRIMARY KEY,
    cdt_id     BIGINT       NOT NULL REFERENCES public.cdts(id) ON DELETE CASCADE,
    type       VARCHAR(50)  NOT NULL,
    s3_url     TEXT         NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_files_updated_at ON public.files;
CREATE TRIGGER trg_files_updated_at BEFORE UPDATE ON public.files
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX IF NOT EXISTS idx_files_cdt_id ON public.files(cdt_id);

-- ==============================================================
-- bearer_tokens
-- ==============================================================
CREATE TABLE IF NOT EXISTS public.bearer_tokens (
    id         BIGSERIAL    PRIMARY KEY,
    user_id    BIGINT       NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    token_hash CHAR(64)     UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ  NOT NULL,
    revoked_at TIMESTAMPTZ  NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_bearer_tokens_updated_at ON public.bearer_tokens;
CREATE TRIGGER trg_bearer_tokens_updated_at BEFORE UPDATE ON public.bearer_tokens
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX IF NOT EXISTS idx_bearer_tokens_user_id     ON public.bearer_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_bearer_tokens_expires_at  ON public.bearer_tokens(expires_at);

-- ==============================================================
-- digital_signatures
-- ==============================================================
CREATE TABLE IF NOT EXISTS public.digital_signatures (
    id               BIGSERIAL     PRIMARY KEY,
    cdt_id           BIGINT        NOT NULL REFERENCES public.cdts(id) ON DELETE CASCADE,
    token            VARCHAR(64)   UNIQUE NOT NULL,
    email            VARCHAR(255)  NOT NULL,
    stage            VARCHAR(30)   NOT NULL,
    pdf_key          TEXT          NOT NULL,
    page             INTEGER       NOT NULL DEFAULT 1,
    pos_x            NUMERIC(5,2)  NOT NULL,
    pos_y            NUMERIC(5,2)  NOT NULL,
    cedula_front_key TEXT          NULL,
    cedula_back_key  TEXT          NULL,
    face_key         TEXT          NULL,
    signature_key    TEXT          NULL,
    signed_pdf_key   TEXT          NULL,
    otp_hash         CHAR(64)      NULL,
    otp_expires_at   TIMESTAMPTZ   NULL,
    otp_attempts     INTEGER       NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_digital_signatures_updated_at ON public.digital_signatures;
CREATE TRIGGER trg_digital_signatures_updated_at BEFORE UPDATE ON public.digital_signatures
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX IF NOT EXISTS idx_digital_signatures_cdt_id ON public.digital_signatures(cdt_id);
ALTER TABLE public.digital_signatures ADD COLUMN IF NOT EXISTS doc_hash CHAR(64) NULL;

CREATE TABLE IF NOT EXISTS public.test_runs (
    id          BIGSERIAL    PRIMARY KEY,
    status      VARCHAR(20)  NOT NULL,
    results     TEXT         NOT NULL DEFAULT '[]',
    finished_at TIMESTAMPTZ  NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
DROP TRIGGER IF EXISTS trg_test_runs_updated_at ON public.test_runs;
CREATE TRIGGER trg_test_runs_updated_at BEFORE UPDATE ON public.test_runs
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
