"""Lambda `cdts-<stage>-migrations-apply`.

Aplica migraciones SQL pendientes a la BD Postgres del stage.

Flujo:
    1. Lee credenciales de SSM (via utils.db.load_db_config).
    2. Abre conexion.
    3. Crea la tabla schema_migrations si no existe (en el schema del stage).
    4. Enumera los archivos backend/platform/migrations/sql/*.sql en orden
       lexicografico.
    5. Para cada archivo NO registrado aun:
        - Abre transaccion.
        - SET LOCAL search_path TO <stage>.
        - Ejecuta el bloque `up` completo.
        - INSERT en schema_migrations.
        - COMMIT.
    6. Devuelve un resumen JSON.

Si un .sql falla, la transaccion rollback, se registra el error, se aborta el
resto (no continua con los siguientes). Como cada archivo es su propia
transaccion, no queda estado intermedio.

El schema al que apuntar (`dev` o `pro`) sale del env `STAGE` que inyecta el
serverless.yml. La misma imagen de la Lambda corre en los dos stages sin
cambios de codigo.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

# Los .sql viajan empaquetados en la Lambda dentro de /var/task/sql/.
# En __file__ = /var/task/src/handlers/apply/handler.py -> subir 3 niveles.
_SQL_DIR = Path(__file__).resolve().parents[3] / "sql"

# Ajuste del sys.path para poder importar utils/ desde el bundle.
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from utils.db import load_db_config, open_connection  # noqa: E402
from utils.parser import parse, MigrationParseError  # noqa: E402


log = logging.getLogger()
log.setLevel(logging.INFO)


def _list_sql_files() -> List[Path]:
    if not _SQL_DIR.exists():
        return []
    return sorted(p for p in _SQL_DIR.glob("*.sql") if p.is_file())


def _ensure_migrations_table(conn, schema: str) -> None:
    """Crea schema_migrations si no existe (en el schema indicado).

    Fuera de transaccion explicita; usa SET search_path a nivel de sesion.
    """
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
    """Aplica una migracion en su propia transaccion.

    Usa SET LOCAL search_path para que solo dure esta tx.
    """
    conn.run("BEGIN")
    try:
        conn.run(f'SET LOCAL search_path TO "{schema}"')
        # pg8000 puede ejecutar multiples statements en un solo run() si estan
        # separados por ';'. Si el usuario ya termino statements con ';', OK.
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
        "Iniciando migrations apply. stage=%s schema=%s host=%s db=%s user=%s",
        stage, schema, cfg["host"], cfg["name"], cfg["user"],
    )
    if schema != stage:
        log.warning(
            "SSM schema='%s' != STAGE='%s'. Usando SSM schema como fuente de verdad.",
            schema, stage,
        )

    sql_files = _list_sql_files()
    log.info("Descubiertos %d archivos .sql en %s", len(sql_files), _SQL_DIR)

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
        log.info("Ya aplicadas: %d", len(already))

        for sql_file in sql_files:
            version = sql_file.stem  # sin .sql
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
            log.info("Aplicando %s ...", version)
            try:
                _apply_one(conn, schema, version, m.up_sql)
                result["applied"].append(version)
                log.info("OK %s", version)
            except Exception as exc:
                result["error"] = f"apply {version}: {type(exc).__name__}: {exc}"
                log.exception("Fallo aplicando %s", version)
                break
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass

    log.info("Resultado: %s", json.dumps(result))
    if result["error"]:
        # Devolver 500 para que aws lambda invoke marque el run como failed
        # (invocacion sincrona desde el pipeline).
        raise RuntimeError(result["error"])
    return result
