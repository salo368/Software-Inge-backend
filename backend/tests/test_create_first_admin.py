"""Unit tests for scripts/create-first-admin.py (the DB part, with a fake
connection: no network, no AWS)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create-first-admin.py"
_spec = importlib.util.spec_from_file_location("create_first_admin", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


class FakeConn:
    """Records every statement; answers the three queries the script makes."""

    def __init__(self, existing_admins=0):
        self.existing = existing_admins
        self.calls = []

    def run(self, sql, **params):
        self.calls.append((" ".join(sql.split()), params))
        if sql.startswith("SELECT COUNT"):
            return [(self.existing,)]
        if sql.startswith("INSERT INTO admins"):
            return [("admin-uuid",)]
        return []

    @property
    def statements(self):
        return [sql.split()[0] for sql, _ in self.calls]


def test_creates_admin_and_credentials_in_one_transaction():
    conn = FakeConn(existing_admins=0)

    admin_id = script.create_first_admin(conn, "root@co.co", "Root Admin", "hash")

    assert admin_id == "admin-uuid"
    assert conn.statements == ["BEGIN", "LOCK", "SELECT", "INSERT", "INSERT", "COMMIT"]
    assert ("INSERT INTO admins (email, full_name) VALUES (:email, :full_name) RETURNING id",
            {"email": "root@co.co", "full_name": "Root Admin"}) in conn.calls
    assert ("INSERT INTO admin_credentials (admin_id, password_hash) VALUES (:admin_id, :password_hash)",
            {"admin_id": "admin-uuid", "password_hash": "hash"}) in conn.calls


def test_locks_the_table_before_checking_so_two_runs_cannot_both_pass():
    conn = FakeConn()

    script.create_first_admin(conn, "root@co.co", "Root", "hash")

    assert conn.statements.index("LOCK") < conn.statements.index("SELECT")


def test_refuses_when_an_admin_already_exists_and_inserts_nothing():
    conn = FakeConn(existing_admins=1)

    with pytest.raises(script.AdminAlreadyExists):
        script.create_first_admin(conn, "other@co.co", "Other", "hash")

    assert "INSERT" not in conn.statements
    assert conn.statements[-1] == "ROLLBACK"


def test_rolls_back_if_the_credentials_insert_fails():
    class Failing(FakeConn):
        def run(self, sql, **params):
            if sql.startswith("INSERT INTO admin_credentials"):
                raise RuntimeError("boom")
            return super().run(sql, **params)

    conn = Failing()

    with pytest.raises(RuntimeError):
        script.create_first_admin(conn, "root@co.co", "Root", "hash")

    assert "COMMIT" not in conn.statements
    assert conn.statements[-1] == "ROLLBACK"
