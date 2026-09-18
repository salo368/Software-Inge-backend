"""Parser de archivos .sql de migracion.

Formato esperado:

    -- +migrate up
    <statements SQL a aplicar>

    -- +migrate down
    <statements SQL para rollback (opcional)>

- La seccion `up` es obligatoria.
- La seccion `down` es opcional.
- Los marcadores `-- +migrate up` / `-- +migrate down` son case-insensitive y
  pueden tener espacios extra alrededor.
- Cualquier texto antes del primer marcador es ignorado (util para comentario
  de cabecera del archivo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_MARKER_UP = re.compile(r"^\s*--\s*\+migrate\s+up\b", re.IGNORECASE | re.MULTILINE)
_MARKER_DOWN = re.compile(r"^\s*--\s*\+migrate\s+down\b", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Migration:
    version: str  # nombre del archivo sin .sql (ej. 20260918153000_create_users)
    up_sql: str
    down_sql: Optional[str]


class MigrationParseError(ValueError):
    """La migracion no cumple el formato esperado."""


def parse(version: str, content: str) -> Migration:
    up_match = _MARKER_UP.search(content)
    if not up_match:
        raise MigrationParseError(
            f"'{version}': falta la seccion '-- +migrate up'."
        )

    down_match = _MARKER_DOWN.search(content, up_match.end())

    if down_match:
        up_sql = content[up_match.end() : down_match.start()].strip()
        down_sql: Optional[str] = content[down_match.end() :].strip() or None
    else:
        up_sql = content[up_match.end() :].strip()
        down_sql = None

    if not up_sql:
        raise MigrationParseError(
            f"'{version}': la seccion '-- +migrate up' esta vacia."
        )

    return Migration(version=version, up_sql=up_sql, down_sql=down_sql)
