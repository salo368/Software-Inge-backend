#!/usr/bin/env python3
"""Lint SQL migration files. See backend/platform/migrations/README.md."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

SQL_DIR = Path("backend/platform/migrations/sql")

FILENAME_RE = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")

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
    # Preserve line count by keeping \n and replacing content with spaces/empties.
    sql = re.sub(
        r"/\*[\s\S]*?\*/",
        lambda m: "".join(c if c == "\n" else " " for c in m.group(0)),
        sql,
    )
    sql = re.sub(r"E'(?:\\.|'{2}|[^'\\])*'", "''", sql, flags=re.IGNORECASE)
    sql = re.sub(r"'(?:''|[^'])*'", "''", sql)
    sql = re.sub(r'"(?:""|[^"])*"', '""', sql)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def check_file(path: Path) -> List[str]:
    errors: List[str] = []

    if not FILENAME_RE.match(path.name):
        errors.append(
            f"naming: {path.name!r} does not match "
            "'YYYYMMDDHHMMSS_snake_case.sql' "
            "(e.g. '20260918153000_create_users_table.sql')"
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"encoding: not valid UTF-8 ({exc})")
        return errors

    if not UP_MARKER_RE.search(raw):
        errors.append("structure: missing required '-- +migrate up' section")

    cleaned = strip_sql_noise(raw)

    m = SCHEMA_QUALIFIER_RE.search(cleaned)
    if m:
        errors.append(
            f"schema-qualifier: {m.group(0)!r} at line "
            f"{line_of(cleaned, m.start())}. Migrations must not qualify schema; "
            "the Lambda sets 'SET LOCAL search_path TO <stage>'. Write "
            "'CREATE TABLE users', not 'CREATE TABLE dev.users'."
        )

    m = SET_SEARCH_PATH_RE.search(cleaned)
    if m:
        errors.append(
            f"set-search-path: forbidden at line {line_of(cleaned, m.start())}"
        )

    m = CREATE_SCHEMA_RE.search(cleaned)
    if m:
        errors.append(
            f"create-schema: forbidden at line {line_of(cleaned, m.start())}"
        )

    m = DROP_SCHEMA_RE.search(cleaned)
    if m:
        errors.append(
            f"drop-schema: forbidden at line {line_of(cleaned, m.start())}"
        )

    return errors


def main(argv: List[str]) -> int:
    if len(argv) > 1:
        targets: List[Path] = [Path(p) for p in argv[1:]]
    else:
        if not SQL_DIR.exists():
            print(f"[lint-migrations] {SQL_DIR}/ not present, nothing to check.")
            return 0
        targets = sorted(SQL_DIR.glob("*.sql"))
        if not targets:
            print(f"[lint-migrations] {SQL_DIR}/ is empty, nothing to check.")
            return 0

    total_errors = 0
    files_with_errors = 0
    for f in targets:
        if not f.exists():
            print(f"WARN: {f} does not exist, skip.")
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
            f"[lint-migrations] FAIL: {total_errors} violation(s) in "
            f"{files_with_errors} file(s) (of {len(targets)} checked)."
        )
        return 1

    print(f"[lint-migrations] OK: {len(targets)} file(s) clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
