"""Applies pending SQL migrations to the stage schema."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[3]
_SQL_DIR = _ROOT / "sql"
sys.path.insert(0, str(_ROOT))

from utils.db import load_db_config, open_connection  # noqa: E402
from utils.parser import parse, MigrationParseError  # noqa: E402


log = logging.getLogger()
log.setLevel(logging.INFO)


def _list_sql_files() -> List[Path]:
    if not _SQL_DIR.exists():
        return []
    return sorted(p for p in _SQL_DIR.glob("*.sql") if p.is_file())


def _ensure_migrations_table(conn, schema: str) -> None:
    conn.run(f'SET search_path TO "{schema}"')
    conn.run(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _already_applied(conn, schema: str) -> set[str]:
    conn.run(f'SET search_path TO "{schema}"')
    rows = conn.run("SELECT version FROM schema_migrations")
    return {r[0] for r in rows}


def _apply_one(conn, schema: str, version: str, up_sql: str) -> None:
    conn.run("BEGIN")
    try:
        conn.run(f'SET LOCAL search_path TO "{schema}"')
        conn.run(up_sql)
        conn.run(
            "INSERT INTO schema_migrations (version) VALUES (:v)",
            v=version,
        )
        conn.run("COMMIT")
    except Exception:
        conn.run("ROLLBACK")
        raise


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    stage = os.environ["STAGE"]
    cfg = load_db_config()
    schema = cfg["schema"]
    log.info(
        "start stage=%s schema=%s host=%s db=%s user=%s",
        stage, schema, cfg["host"], cfg["name"], cfg["user"],
    )
    if schema != stage:
        log.warning("SSM schema=%r != STAGE=%r; using SSM schema", schema, stage)

    sql_files = _list_sql_files()
    log.info("discovered %d .sql files in %s", len(sql_files), _SQL_DIR)

    result: Dict[str, Any] = {
        "stage": stage,
        "schema": schema,
        "discovered": [p.name for p in sql_files],
        "applied": [],
        "skipped": [],
        "error": None,
    }

    conn = open_connection(cfg)
    try:
        _ensure_migrations_table(conn, schema)
        already = _already_applied(conn, schema)
        log.info("already applied: %d", len(already))

        for sql_file in sql_files:
            version = sql_file.stem
            if version in already:
                result["skipped"].append(version)
                continue
            content = sql_file.read_text(encoding="utf-8")
            try:
                m = parse(version, content)
            except MigrationParseError as exc:
                result["error"] = f"parse: {exc}"
                log.error(str(exc))
                break
            log.info("applying %s", version)
            try:
                _apply_one(conn, schema, version, m.up_sql)
                result["applied"].append(version)
                log.info("ok %s", version)
            except Exception as exc:
                result["error"] = f"apply {version}: {type(exc).__name__}: {exc}"
                log.exception("failed applying %s", version)
                break
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass

    log.info("result: %s", json.dumps(result))
    if result["error"]:
        raise RuntimeError(result["error"])
    return result
