"""Aplica scripts/db_init.sql sobre la RDS leyendo credenciales de SSM.

Uso:
    python scripts/db_init.py                # stage=dev por default
    STAGE=tes python scripts/db_init.py      # otro stage
"""
import os
import sys
from pathlib import Path

import boto3
import pg8000


def get_ssm_params(stage: str) -> dict:
    ssm = boto3.client("ssm")
    resp = ssm.get_parameters_by_path(Path=f"/cdts/{stage}/db", WithDecryption=True)
    return {p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in resp["Parameters"]}


def main() -> int:
    stage = os.environ.get("STAGE", "dev")
    print(f"Stage: {stage}")

    p = get_ssm_params(stage)
    missing = [k for k in ("host", "port", "name", "user", "password") if k not in p]
    if missing:
        print(f"Faltan parametros en SSM: {missing}", file=sys.stderr)
        return 1

    sql_path = Path(__file__).parent / "db_init.sql"
    sql = sql_path.read_text(encoding="utf-8")

    print(f"Conectando a {p['host']}:{p['port']}/{p['name']} como {p['user']}...")
    conn = pg8000.connect(
        host=p["host"],
        port=int(p["port"]),
        database=p["name"],
        user=p["user"],
        password=p["password"],
    )
    conn.autocommit = False

    try:
        cur = conn.cursor()
        print("Ejecutando DDL...")
        cur.execute(sql)
        conn.commit()

        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
        )
        tables = [r[0] for r in cur.fetchall()]

        print(f"\nTablas en public ({len(tables)}):")
        for t in tables:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position;",
                (t,),
            )
            cols = cur.fetchall()
            print(f"  - {t}  ({len(cols)} columnas)")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
