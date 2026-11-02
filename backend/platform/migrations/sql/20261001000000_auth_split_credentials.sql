-- Splits password_hash out of `users` into its own `user_credentials`
-- table (1:1 via user_id). `users` should only ever hold non-critical
-- profile data so Users.public_dict() can be a plain allowlist, same
-- shape as every other ORM model, instead of a to_dict()+pop blocklist
-- that silently leaks the next sensitive column someone adds.
--
-- Paired changes:
--   * libs/orm/users.py             (drop password_hash field)
--   * libs/orm/user_credentials.py  (new)
--   * services/auth/src/handlers/register/handler.py
--   * services/auth/src/handlers/login/handler.py
--   * backend/tests/integration_helpers.py

-- +migrate up

CREATE TABLE user_credentials (
    user_id        UUID         PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    password_hash  TEXT         NOT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

INSERT INTO user_credentials (user_id, password_hash, created_at, updated_at)
SELECT id, password_hash, created_at, updated_at FROM users;

ALTER TABLE users DROP COLUMN password_hash;

-- +migrate down

ALTER TABLE users ADD COLUMN password_hash TEXT;

UPDATE users u
SET password_hash = c.password_hash
FROM user_credentials c
WHERE c.user_id = u.id;

ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL;

DROP TABLE user_credentials;
