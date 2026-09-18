#!/usr/bin/env python3
"""Lint SQL migrations before applying them.

Enforces conventions defined in backend/platform/migrations/README.md and
docs/repo-structure.md sections 11 and 14:

- No schema qualifiers (dev., pro., public.). El schema lo fija la Lambda al
  invocar via SET LOCAL search_path.
- No SET search_path en los .sql (responsabilidad exclusiva de la Lambda).
- No CREATE SCHEMA / DROP SCHEMA (los schemas dev y pro existen fuera del
  pipeline; nunca se crean/borran desde una migracion).
- Nombre de archivo: YYYYMMDDHHMMSS_snake_case.sql.
- Debe existir al menos la seccion '-- +migrate up'.

Uso:
    python scripts/ci/lint-migrations.py
    # Codigo de salida 0 si OK, 1 si hay violaciones.

Filosofia: mejor un falso positivo raro (que se corrige renombrando algo) que
permitir que un CREATE TABLE dev.users llegue a produccion silenciosamente.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Tuple

SQL_DIR = Path("backend/platform/migrations/sql")

FILENAME_RE = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")

# Solo bloqueamos los schemas conocidos del proyecto. Si en el futuro se agrega
# otro schema legitimo (ej. una extension como 'pg_catalog'), se mantiene fuera
# de esta lista y no genera falso positivo.
FORBIDDEN_SCHEMAS = ("dev", "pro", "public")
SCHEMA_QUALIFIER_RE = re.compile(
    r"\b(" + "|".join(FORBIDDEN_SCHEMAS) + r")\s*\.\s*[a-zA-Z_\"]",
    re.IGNORECASE,
)

SET_SEARCH_PATH_RE = re.compile(
    r"\bset\s+(?:local\s+|session\s+)?search_path\b",
    re.IGNORECASE,
)

CREATE_SCHEMA_RE = re.compile(r"\bcreate\s+schema\b", re.IGNORECASE)
DROP_SCHEMA_RE = re.compile(r"\bdrop\s+schema\b", re.IGNORECASE)

UP_MARKER_RE = re.compile(
    r"^\s*--\s*\+migrate\s+up\b",
    re.IGNORECASE | re.MULTILINE,
)


def strip_sql_noise(sql: str) -> str:
    """Remove block/line comments and string/quoted-identifier literals.

    Preserva la posicion aproximada de las lineas reemplazando con espacios
    (mantiene los \\n).
    """
    # /* block comments */
    sql = re.sub(
        r"/\*[\s\S]*?\*/",
        lambda m: "".join(c if c == "\n" else " " for c in m.group(0)),
        sql,
    )
    # E'...' escape strings (antes que 'literal' plain)
    sql = re.sub(
        r"E'(?:\\.|'{2}|[^'\\])*'",
        "''",
        sql,
        flags=re.IGNORECASE,
    )
    # 'literal strings' (soportan '' escapado)
    sql = re.sub(r"'(?:''|[^'])*'", "''", sql)
    # "quoted identifiers"
    sql = re.sub(r'"(?:""|[^"])*"', '""', sql)
    # -- line comments (despues, para no comerse '--' dentro de strings)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def check_file(path: Path) -> List[str]:
    errors: List[str] = []

    if not FILENAME_RE.match(path.name):
        errors.append(
            "naming: nombre '"
            + path.name
            + "' no matchea 'YYYYMMDDHHMMSS_snake_case.sql'. "
            "Ej: '20260918153000_create_users_table.sql'."
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"encoding: no se pudo leer como UTF-8 ({exc}).")
        return errors

    if not UP_MARKER_RE.search(raw):
        errors.append(
            "structure: falta la seccion '-- +migrate up' (obligatoria)."
        )

    cleaned = strip_sql_noise(raw)

    m = SCHEMA_QUALIFIER_RE.search(cleaned)
    if m:
        errors.append(
            "schema-qualifier: uso de '"
            + m.group(0)
            + "' en linea "
            + str(line_of(cleaned, m.start()))
            + ". Las migraciones NO deben calificar schema; la Lambda hace "
            "'SET LOCAL search_path TO <stage>'. Escribi 'CREATE TABLE users' "
            "en lugar de 'CREATE TABLE dev.users'."
        )

    m = SET_SEARCH_PATH_RE.search(cleaned)
    if m:
        errors.append(
            "set-search-path: 'SET search_path' prohibido en linea "
            + str(line_of(cleaned, m.start()))
            + ". Es responsabilidad exclusiva de la Lambda de migrations."
        )

    m = CREATE_SCHEMA_RE.search(cleaned)
    if m:
        errors.append(
            "create-schema: 'CREATE SCHEMA' prohibido en linea "
            + str(line_of(cleaned, m.start()))
            + ". Los schemas 'dev' y 'pro' se crean fuera del pipeline."
        )

    m = DROP_SCHEMA_RE.search(cleaned)
    if m:
        errors.append(
            "drop-schema: 'DROP SCHEMA' prohibido en linea "
            + str(line_of(cleaned, m.start()))
            + "."
        )

    return errors


def main(argv: List[str]) -> int:
    # Permite pasar rutas custom para testear localmente.
    if len(argv) > 1:
        targets: List[Path] = [Path(p) for p in argv[1:]]
    else:
        if not SQL_DIR.exists():
            print(f"[lint-migrations] {SQL_DIR}/ no existe todavia; nada que validar.")
            return 0
        targets = sorted(SQL_DIR.glob("*.sql"))
        if not targets:
            print(f"[lint-migrations] {SQL_DIR}/ esta vacio; nada que validar.")
            return 0

    total_errors = 0
    files_with_errors = 0
    for f in targets:
        if not f.exists():
            print(f"WARN: {f} no existe; skip.")
            continue
        errs = check_file(f)
        if errs:
            files_with_errors += 1
            print(f"\n{f}")
            for e in errs:
                print(f"  ERROR: {e}")
            total_errors += len(errs)

    print()
    if total_errors:
        print(
            f"[lint-migrations] FAIL: {total_errors} violacion(es) en "
            f"{files_with_errors} archivo(s) (de {len(targets)} validados)."
        )
        return 1

    print(f"[lint-migrations] OK: {len(targets)} archivo(s) sin violaciones.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
