from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MIGRATIONS_DIR = _HERE.parent / "platform" / "migrations"
sys.path.insert(0, str(_MIGRATIONS_DIR))

from utils.parser import parse, Migration, MigrationParseError  # noqa: E402


def test_parse_with_up_and_down():
    content = """
-- header comment
-- +migrate up
CREATE TABLE users (id UUID PRIMARY KEY);
CREATE INDEX users_id_idx ON users (id);

-- +migrate down
DROP INDEX users_id_idx;
DROP TABLE users;
"""
    m = parse("20260918_users", content)
    assert isinstance(m, Migration)
    assert m.version == "20260918_users"
    assert "CREATE TABLE users" in m.up_sql
    assert "CREATE INDEX users_id_idx" in m.up_sql
    assert "-- +migrate down" not in m.up_sql
    assert m.down_sql is not None
    assert "DROP TABLE users" in m.down_sql


def test_parse_with_only_up():
    content = """-- +migrate up
CREATE TABLE stuff (id UUID);
"""
    m = parse("20260918_only_up", content)
    assert m.up_sql.startswith("CREATE TABLE stuff")
    assert m.down_sql is None


def test_parse_case_insensitive_markers():
    content = """
-- +MIGRATE UP
SELECT 1;

-- +Migrate Down
SELECT 2;
"""
    m = parse("v", content)
    assert "SELECT 1" in m.up_sql
    assert m.down_sql is not None
    assert "SELECT 2" in m.down_sql


def test_parse_extra_whitespace_in_markers():
    content = """--   +migrate    up
INSERT INTO x VALUES (1);
"""
    m = parse("v", content)
    assert "INSERT INTO x VALUES" in m.up_sql
    assert m.down_sql is None


def test_parse_fails_without_up():
    content = """-- +migrate down
DROP TABLE something;
"""
    with pytest.raises(MigrationParseError, match="missing"):
        parse("v", content)


def test_parse_fails_when_up_empty():
    content = """-- +migrate up

-- +migrate down
DROP TABLE x;
"""
    with pytest.raises(MigrationParseError, match="empty"):
        parse("v", content)


def test_parse_ignores_marker_not_at_start_of_line():
    # `-- +migrate down` inside a string literal must not be treated as marker.
    content = """-- +migrate up
INSERT INTO logs (msg) VALUES ('hello -- +migrate down does not count');
CREATE TABLE x (id UUID);
"""
    m = parse("v", content)
    assert "CREATE TABLE x" in m.up_sql
    assert m.down_sql is None
