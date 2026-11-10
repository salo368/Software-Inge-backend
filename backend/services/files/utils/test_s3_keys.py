"""Unit tests for the files-block `s3_keys` util (loaded by path, like the
sibling investment_order test, to avoid the block-local `utils` binding)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

_spec = importlib.util.spec_from_file_location("s3_keys", Path(__file__).resolve().parent / "s3_keys.py")
s3_keys = importlib.util.module_from_spec(_spec)
sys.modules["s3_keys"] = s3_keys
_spec.loader.exec_module(s3_keys)


def test_build_file_key_layout():
    pid, fid = uuid4(), uuid4()
    assert s3_keys.build_file_key(pid, "RUT", fid, ".pdf") == f"processes/{pid}/RUT/{fid}.pdf"


def test_build_file_key_accepts_enum_and_no_extension():
    from enum import Enum

    class T(str, Enum):
        X = "X"

    pid, fid = uuid4(), uuid4()
    assert s3_keys.build_file_key(pid, T.X, fid) == f"processes/{pid}/X/{fid}"


def test_build_file_metadata():
    pid = uuid4()
    assert s3_keys.build_file_metadata(pid, "RUT", "a%20b.pdf") == {
        "process-id": str(pid), "file-type": "RUT", "original-name": "a%20b.pdf",
    }
