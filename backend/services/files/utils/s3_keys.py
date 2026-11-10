"""Single source of truth for how objects are laid out in the files bucket.

Every lambda that writes to the bucket builds its key here, so changing the
convention is a one-place change. Nothing may read information back out of a
key: process_id / file_type travel in the object metadata (see `metadata`).
"""
from __future__ import annotations

from enum import Enum
from uuid import UUID


def _value(file_type) -> str:
    return file_type.value if isinstance(file_type, Enum) else str(file_type)


def build_file_key(process_id: UUID | str, file_type, file_id: UUID | str, ext: str = "") -> str:
    return f"processes/{process_id}/{_value(file_type)}/{file_id}{ext}"


def build_file_metadata(process_id: UUID | str, file_type, original_name: str) -> dict[str, str]:
    """Object metadata `on_upload` registers the file from. `original_name`
    must already be ASCII (percent-encode it first)."""
    return {
        "process-id": str(process_id),
        "file-type": _value(file_type),
        "original-name": original_name,
    }
