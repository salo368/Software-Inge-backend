-- Admins (internal users): same shape as users + user_credentials + their
-- tokens, in their own tables. bearer_tokens is renamed to
-- user_bearer_tokens so each kind of token lives in its own table, with a
-- foreign key to its own subject.

-- +migrate up

CREATE TABLE IF NOT EXISTS admins (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR(320)  NOT NULL UNIQUE,
    full_name   VARCHAR(200)  NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_credentials (
    admin_id       UUID         PRIMARY KEY REFERENCES admins(id) ON DELETE CASCADE,
    password_hash  TEXT         NOT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE IF EXISTS bearer_tokens RENAME TO user_bearer_tokens;
ALTER INDEX IF EXISTS bearer_tokens_user_id_idx RENAME TO user_bearer_tokens_user_id_idx;
ALTER INDEX IF EXISTS bearer_tokens_expires_at_idx RENAME TO user_bearer_tokens_expires_at_idx;

CREATE TABLE IF NOT EXISTS admin_bearer_tokens (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id    UUID         NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    token_hash  CHAR(64)     NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ  NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS admin_bearer_tokens_admin_id_idx ON admin_bearer_tokens (admin_id);
CREATE INDEX IF NOT EXISTS admin_bearer_tokens_expires_at_idx ON admin_bearer_tokens (expires_at);

-- +migrate down

DROP TABLE IF EXISTS admin_bearer_tokens;

ALTER INDEX IF EXISTS user_bearer_tokens_expires_at_idx RENAME TO bearer_tokens_expires_at_idx;
ALTER INDEX IF EXISTS user_bearer_tokens_user_id_idx RENAME TO bearer_tokens_user_id_idx;
ALTER TABLE IF EXISTS user_bearer_tokens RENAME TO bearer_tokens;

DROP TABLE IF EXISTS admin_credentials;
DROP TABLE IF EXISTS admins;
