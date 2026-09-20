"""Unit tests for the platform/migrations/apply Lambda.

The handler does not use the shared `@handle_exceptions` decorator, so no
`libs/` neutralization is needed. We only mock the DB connection and swap the
SQL directory for a temp path with fake migration files.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


def _write_sql(dir_path, name: str, up: str = "SELECT 1", down: str | None = None) -> None:
    body = f"-- +migrate up\n{up}\n"
    if down is not None:
        body += f"-- +migrate down\n{down}\n"
    (dir_path / f"{name}.sql").write_text(body, encoding="utf-8")


def _fake_conn():
    """A fake pg8000 connection: `run(sql)` returns rows when it looks like a
    SELECT, and no-op otherwise. Tests can override attributes as needed."""
    conn = MagicMock()
    conn.run = MagicMock(return_value=[])
    return conn


def test_apply_happy_path_applies_only_unapplied(load_handler, monkeypatch, tmp_path):
    h = load_handler(__file__)
    os.environ["STAGE"] = "test"

    # Two migration files on disk; one is already applied per the DB.
    _write_sql(tmp_path, "20260101_a", "CREATE TABLE a(id int)")
    _write_sql(tmp_path, "20260102_b", "CREATE TABLE b(id int)")
    monkeypatch.setattr(h, "_SQL_DIR", tmp_path)

    monkeypatch.setattr(
        h,
        "load_db_config",
        MagicMock(return_value={
            "host": "x", "port": "5432", "name": "d", "user": "u",
            "password": "p", "schema": "test",
        }),
    )
    conn = _fake_conn()
    # `_already_applied` reads rows from the DB; simulate that 20260101_a is
    # already there so only 20260102_b should be applied.
    conn.run.side_effect = lambda sql, **_: (
        [("20260101_a",)] if "SELECT version" in sql else []
    )
    monkeypatch.setattr(h, "open_connection", MagicMock(return_value=conn))

    result = h.handler({}, None)

    assert result["stage"] == "test"
    assert result["schema"] == "test"
    assert result["applied"] == ["20260102_b"]
    assert result["skipped"] == ["20260101_a"]
    assert result["error"] is None


def test_apply_no_sql_files_is_a_noop(load_handler, monkeypatch, tmp_path):
    h = load_handler(__file__)
    os.environ["STAGE"] = "test"
    monkeypatch.setattr(h, "_SQL_DIR", tmp_path)  # empty tmp

    monkeypatch.setattr(
        h,
        "load_db_config",
        MagicMock(return_value={
            "host": "x", "port": "5432", "name": "d", "user": "u",
            "password": "p", "schema": "test",
        }),
    )
    monkeypatch.setattr(h, "open_connection", MagicMock(return_value=_fake_conn()))

    result = h.handler({}, None)

    assert result["applied"] == []
    assert result["skipped"] == []
    assert result["discovered"] == []
    assert result["error"] is None


def test_apply_parse_error_stops_the_loop_and_raises(load_handler, monkeypatch, tmp_path):
    h = load_handler(__file__)
    os.environ["STAGE"] = "test"

    # Malformed migration: no `-- +migrate up` marker at all.
    (tmp_path / "20260103_bad.sql").write_text("SELECT 1;\n", encoding="utf-8")
    monkeypatch.setattr(h, "_SQL_DIR", tmp_path)

    monkeypatch.setattr(
        h,
        "load_db_config",
        MagicMock(return_value={
            "host": "x", "port": "5432", "name": "d", "user": "u",
            "password": "p", "schema": "test",
        }),
    )
    monkeypatch.setattr(h, "open_connection", MagicMock(return_value=_fake_conn()))

    with pytest.raises(RuntimeError, match="parse:"):
        h.handler({}, None)
