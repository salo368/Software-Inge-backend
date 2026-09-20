"""Pytest bootstrap for the whole backend suite.

This file MUST stay lean and side-effect-only-at-import. Pytest loads it once
before collecting any test module (including the colocated `test.py` files
that live next to each Lambda's `handler.py`), so this is where we
neutralize the AWS calls and native drivers that `libs/core/db.py` fires at
import time. Without this, doing `from services.auth.src.handlers.login.handler
import handler` inside a unit test would immediately try to hit real SSM to
load DB credentials and crash the whole suite.

Contract for the colocated tests:

  * `boto3` is stubbed. Any call to `boto3.client(<service>).<any_method>(...)`
    returns a harmless fake value (SSM path lookups return five fake DB
    params; anything else returns a MagicMock). Tests that need a specific
    AWS behaviour can still `monkeypatch` the client reference inside the
    handler module.
  * DB env vars (`STAGE`, `SSM_DB_PATH`) are set to safe defaults.
  * The SQLAlchemy engine is created but never opens a connection unless a
    query actually runs. Tests MUST monkeypatch the ORM entrypoints they
    exercise (e.g. `Users.get_by_email`) so no real query fires.
  * The `load_handler` fixture below imports the sibling `handler.py` of the
    currently-running `test.py` under a unique module name and returns the
    module. Tests then monkeypatch names on that module.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# 0) `--integration` flag: colocated `integration.py` tests hit real deployed
#    infra (dev API Gateway + Postgres + S3). They MUST NOT run on a plain
#    local `pytest` invocation, so we auto-skip anything marked
#    `@pytest.mark.integration` unless `--integration` is passed. The CI
#    integration job passes it; unit runs (local or `tests` job) do not.
# ---------------------------------------------------------------------------
def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Also run integration.py tests that hit real dev AWS/DB. "
             "Without this flag, tests marked @pytest.mark.integration are "
             "collected but skipped, so a plain `pytest` never touches infra.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--integration"):
        return
    skip_marker = pytest.mark.skip(
        reason="pass --integration to run tests that hit real dev infra"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)

# ---------------------------------------------------------------------------
# 1) Make `backend/` importable so tests can do `from libs.core... import ...`
#    exactly like Lambda does at runtime (Lambda's cwd is the zip root, which
#    mirrors `backend/` after packaging).
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# ---------------------------------------------------------------------------
# 2) Default env for anything that reads envs at import time.
# ---------------------------------------------------------------------------
os.environ.setdefault("STAGE", "test")
os.environ.setdefault("SSM_DB_PATH", "/cdts/test/db")
os.environ.setdefault("FILES_BUCKET", "cdts-test-files")
os.environ.setdefault("ASSETS_BASE_URL", "https://assets.test")

# ---------------------------------------------------------------------------
# 3) Stub `boto3` BEFORE any handler imports libs.core.db.
#    A tiny fake client returns:
#      - a well-formed SSM parameters-by-path payload so `_load_db_config()`
#        builds a valid dict and the engine URL formats cleanly,
#      - a MagicMock for every other method (rekognition, s3, ses, ...).
#    Since the SQLAlchemy engine is lazy, no real connection is opened.
# ---------------------------------------------------------------------------
class _FakeAWSClient:
    def get_parameters_by_path(self, Path, WithDecryption=False):  # noqa: N803
        base = Path.rstrip("/")
        return {
            "Parameters": [
                {"Name": f"{base}/host", "Value": "localhost"},
                {"Name": f"{base}/port", "Value": "5432"},
                {"Name": f"{base}/name", "Value": "test"},
                {"Name": f"{base}/user", "Value": "test"},
                {"Name": f"{base}/password", "Value": "test"},
                {"Name": f"{base}/schema", "Value": "test"},
            ]
        }

    def get_parameter(self, Name, WithDecryption=False):  # noqa: N803
        return {"Parameter": {"Name": Name, "Value": ""}}

    def __getattr__(self, name):
        # Anything else (rekognition.detect_text, s3.put_object, ...) returns
        # a MagicMock so import-time or side-effect calls do not crash.
        return MagicMock()


_fake_boto3 = ModuleType("boto3")
_fake_boto3.client = lambda *a, **kw: _FakeAWSClient()
_fake_boto3.resource = lambda *a, **kw: _FakeAWSClient()
sys.modules["boto3"] = _fake_boto3


# ---------------------------------------------------------------------------
# 4) Fixture: load the sibling handler.py of a colocated test.py.
#
# Usage inside a Lambda's test.py:
#
#     def test_happy_path(load_handler, monkeypatch):
#         h = load_handler(__file__)                       # imports handler.py
#         monkeypatch.setattr(h, "Users", MagicMock(...))  # stub ORM
#         resp = h.handler({"body": "{}"}, None)
#         assert resp["statusCode"] == 200
#
# Each Lambda's handler is imported under a unique module name derived from
# its path, so parallel or sequential collections never collide in
# sys.modules even though every handler file is called `handler.py`.
# ---------------------------------------------------------------------------
_handler_cache: dict[str, ModuleType] = {}


def _find_block_root(p: Path) -> Path | None:
    """Walks up from `p` until it finds the directory that owns a
    `serverless.yml` (the block root). Returns None if no such directory
    exists on the way up to `backend/`. That directory is what `handler.py`
    treats as its import root at runtime, because Serverless packages the
    block-local `utils/`, `data/`, etc. next to the handler in the zip."""
    for parent in p.parents:
        if (parent / "serverless.yml").exists():
            return parent
        if parent == _BACKEND:
            return None
    return None


_BLOCK_LOCAL_PACKAGES = ("utils", "data")


def _purge_block_local_modules() -> None:
    """Evicts block-local namespace packages (`utils`, `data`) and their
    submodules from `sys.modules` so the next handler load re-resolves them
    against the current block's directory. Necessary because Python caches a
    namespace package's `__path__` at first-import time; later `sys.path`
    changes don't extend it."""
    for name in list(sys.modules.keys()):
        if name in _BLOCK_LOCAL_PACKAGES or any(
            name.startswith(pkg + ".") for pkg in _BLOCK_LOCAL_PACKAGES
        ):
            sys.modules.pop(name, None)


def _bind_block_local_packages(block_root: Path) -> None:
    """Explicitly binds `utils` / `data` to the given block's own directory
    (if it exists) so `from utils.emails import X` inside the handler
    resolves against THIS block's utils, not against a stale namespace
    package cached from a previously loaded block. We build a synthetic
    package module and stick it in sys.modules under the top-level name."""
    import importlib.machinery
    for pkg_name in _BLOCK_LOCAL_PACKAGES:
        pkg_dir = block_root / pkg_name
        if not pkg_dir.is_dir():
            continue
        spec = importlib.machinery.ModuleSpec(pkg_name, loader=None, is_package=True)
        spec.submodule_search_locations = [str(pkg_dir)]
        mod = importlib.util.module_from_spec(spec)
        mod.__path__ = [str(pkg_dir)]  # type: ignore[attr-defined]
        sys.modules[pkg_name] = mod


def _load_sibling_handler(test_file: str) -> ModuleType:
    p = Path(test_file).resolve().parent / "handler.py"
    if not p.exists():
        raise FileNotFoundError(
            f"expected handler.py next to {test_file} (Lambda tests must be "
            f"colocated with their handler)"
        )
    key = str(p)
    cached = _handler_cache.get(key)
    if cached is not None:
        return cached
    # Make the block root importable so `from utils.emails import ...` and
    # similar block-local imports resolve exactly like they do at runtime
    # (where Lambda's cwd is the zip root, which mirrors the block dir).
    # We also purge stale `utils`/`data` bindings from sys.modules so Python
    # rebuilds the namespace package against the fresh sys.path, otherwise
    # the first block to import `utils` "wins" for the whole session.
    block_root = _find_block_root(p)
    _purge_block_local_modules()
    if block_root is not None:
        block_str = str(block_root)
        # Ensure block_root is the FIRST entry, not just present.
        while block_str in sys.path:
            sys.path.remove(block_str)
        sys.path.insert(0, block_str)
        # Force `utils` / `data` to resolve to THIS block's dirs. Purging
        # sys.modules alone is not enough because namespace-package finders
        # cache per-directory finders in sys.path_importer_cache; the safest
        # thing is to synthesize the package binding directly.
        _bind_block_local_packages(block_root)
    # Module name based on the three-deep tail of the path so it stays unique
    # per Lambda (e.g. cdts_h_handlers_login, cdts_h_workers_on_upload).
    tail = "_".join(p.parts[-4:-1]).replace("-", "_")
    mod_name = f"cdts_h_{tail}"
    spec = importlib.util.spec_from_file_location(mod_name, p)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    _handler_cache[key] = mod
    return mod


@pytest.fixture
def load_handler():
    """Returns a callable that imports the sibling handler.py of __file__."""
    return _load_sibling_handler
