"""Conexion a Postgres: carga credenciales de SSM y expone engine + sesiones.

- El engine se crea UNA vez por container (cold start) y se reutiliza.
- Cada llamada a get_session() abre una nueva sesion sobre el mismo engine.
"""
import os
from contextlib import contextmanager
from urllib.parse import quote_plus

import boto3
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _load_db_url() -> str:
    ssm = boto3.client("ssm")
    stage = os.environ.get("STAGE", "dev")
    resp = ssm.get_parameters_by_path(Path=f"/cdts/{stage}/db", WithDecryption=True)
    p = {x["Name"].rsplit("/", 1)[-1]: x["Value"] for x in resp["Parameters"]}

    required = ("host", "port", "name", "user", "password")
    missing = [k for k in required if k not in p]
    if missing:
        raise RuntimeError(f"Faltan parametros SSM en /cdts/{stage}/db: {missing}")

    return (
        f"postgresql+pg8000://{p['user']}:{quote_plus(p['password'])}"
        f"@{p['host']}:{p['port']}/{p['name']}"
    )


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(
            _load_db_url(),
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
            future=True,
        )
        _SessionLocal = sessionmaker(
            bind=_engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    return _engine


@contextmanager
def get_session() -> Session:
    """Context manager: abre sesion, hace rollback en excepcion, cierra al salir."""
    get_engine()
    s = _SessionLocal()
    try:
        yield s
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
