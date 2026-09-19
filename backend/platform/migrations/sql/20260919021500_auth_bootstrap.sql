-- Auth bootstrap: users + bearer_tokens (opaque token, sha256 in DB).

-- +migrate up

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id             UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    email          VARCHAR(320)  NOT NULL UNIQUE,
    password_hash  TEXT          NOT NULL,
    full_name      VARCHAR(200)  NOT NULL,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE bearer_tokens (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   CHAR(64)     NOT NULL UNIQUE,
    expires_at   TIMESTAMPTZ  NOT NULL,
    revoked_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX bearer_tokens_user_id_idx    ON bearer_tokens (user_id);
CREATE INDEX bearer_tokens_expires_at_idx ON bearer_tokens (expires_at);

-- +migrate down

DROP TABLE IF EXISTS bearer_tokens;
DROP TABLE IF EXISTS users;
