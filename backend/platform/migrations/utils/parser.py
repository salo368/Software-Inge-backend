"""Parser for .sql migration files with `-- +migrate up/down` sections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_MARKER_UP = re.compile(r"^\s*--\s*\+migrate\s+up\b", re.IGNORECASE | re.MULTILINE)
_MARKER_DOWN = re.compile(r"^\s*--\s*\+migrate\s+down\b", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Migration:
    version: str
    up_sql: str
    down_sql: Optional[str]


class MigrationParseError(ValueError):
    pass


def parse(version: str, content: str) -> Migration:
    up_match = _MARKER_UP.search(content)
    if not up_match:
        raise MigrationParseError(f"{version!r}: missing '-- +migrate up' section")

    down_match = _MARKER_DOWN.search(content, up_match.end())

    if down_match:
        up_sql = content[up_match.end() : down_match.start()].strip()
        down_sql: Optional[str] = content[down_match.end() :].strip() or None
    else:
        up_sql = content[up_match.end() :].strip()
        down_sql = None

    if not up_sql:
        raise MigrationParseError(f"{version!r}: '-- +migrate up' section is empty")

    return Migration(version=version, up_sql=up_sql, down_sql=down_sql)
