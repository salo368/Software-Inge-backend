"""SSM-backed Postgres connection helpers."""

from __future__ import annotations

import os
from typing import Dict

import boto3
import pg8000.native


_REQUIRED_KEYS = ("host", "port", "name", "user", "password", "schema")


def load_db_config() -> Dict[str, str]:
    ssm_path = os.environ["SSM_DB_PATH"].rstrip("/")
    ssm = boto3.client("ssm")
    resp = ssm.get_parameters_by_path(
        Path=ssm_path + "/",
        WithDecryption=True,
        Recursive=False,
    )
    cfg: Dict[str, str] = {}
    for p in resp.get("Parameters", []):
        key = p["Name"].rsplit("/", 1)[-1]
        cfg[key] = p["Value"]

    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise RuntimeError(
            f"missing SSM params under {ssm_path}/: {missing} "
            f"(found: {sorted(cfg.keys())})"
        )
    return cfg


def open_connection(cfg: Dict[str, str]) -> pg8000.native.Connection:
    return pg8000.native.Connection(
        host=cfg["host"],
        port=int(cfg["port"]),
        database=cfg["name"],
        user=cfg["user"],
        password=cfg["password"],
        ssl_context=True,
        timeout=30,
    )
