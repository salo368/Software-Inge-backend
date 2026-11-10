#!/usr/bin/env python3
"""Creates the first admin of a stage.

The admin service has no open registration: `POST /admin-auth/register`
needs an admin token, so the very first admin has to be written straight
into the database. This is that one-time step. It refuses to run when the
stage already has any admin; every later admin is created through the API by
an existing one.

Usage (credentials able to read /cdts/<stage>/db from SSM, with the stage's
database reachable):

    export AWS_PROFILE=cdt AWS_DEFAULT_REGION=us-east-1
    python scripts/create-first-admin.py --stage staging \\
        --email root@example.com --full-name "Root Admin"

The password is asked twice, without echo. For automation it can be given
in the ADMIN_PASSWORD environment variable instead. It is never printed and
only its bcrypt hash is stored.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from libs.utils.passwords import hash_password  # noqa: E402
from libs.utils.validators import password_reason, valid_email  # noqa: E402


class AdminAlreadyExists(Exception):
    pass


def create_first_admin(conn, email: str, full_name: str, password_hash: str):
    """Inserts the admin and its credentials in one transaction. `conn` is a
    pg8000 native connection already pointing at the stage's schema.

    Raises AdminAlreadyExists if the table already has any admin. The table
    is locked first, so two concurrent runs cannot both pass the check."""
    conn.run("BEGIN")
    try:
        conn.run("LOCK TABLE admins IN EXCLUSIVE MODE")
        (count,), = conn.run("SELECT COUNT(*) FROM admins")
        if count:
            raise AdminAlreadyExists(f"the stage already has {count} admin(s)")

        (admin_id,), = conn.run(
            "INSERT INTO admins (email, full_name) VALUES (:email, :full_name) RETURNING id",
            email=email,
            full_name=full_name,
        )
        conn.run(
            "INSERT INTO admin_credentials (admin_id, password_hash) VALUES (:admin_id, :password_hash)",
            admin_id=admin_id,
            password_hash=password_hash,
        )
        conn.run("COMMIT")
    except BaseException:
        conn.run("ROLLBACK")
        raise

    return admin_id


def _db_config(stage: str, region: str) -> dict:
    import boto3

    ssm = boto3.client("ssm", region_name=region)
    config, token = {}, None
    while True:
        kwargs = {"Path": f"/cdts/{stage}/db", "WithDecryption": True}
        if token:
            kwargs["NextToken"] = token
        resp = ssm.get_parameters_by_path(**kwargs)
        config.update({p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in resp.get("Parameters", [])})
        token = resp.get("NextToken")
        if not token:
            break

    missing = [k for k in ("host", "port", "name", "user", "password") if k not in config]
    if missing:
        raise SystemExit(f"/cdts/{stage}/db is missing {missing}: check the credentials and the stage")

    return config


def _read_password() -> str:
    password = os.environ.get("ADMIN_PASSWORD")
    if password:
        return password

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("The passwords do not match")

    return password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stage", required=True, choices=["dev", "staging", "pro"])
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    args = parser.parse_args()

    email = args.email.strip().lower()
    full_name = args.full_name.strip()

    if not valid_email(email):
        raise SystemExit("invalid_email")
    if not full_name:
        raise SystemExit("full_name is required")

    password = _read_password()
    if reason := password_reason(password):
        raise SystemExit(reason)

    import pg8000.native

    cfg = _db_config(args.stage, args.region)
    conn = pg8000.native.Connection(
        user=cfg["user"], password=cfg["password"], host=cfg["host"], port=int(cfg["port"]), database=cfg["name"],
    )
    try:
        conn.run(f'SET search_path TO "{args.stage}", pg_catalog')
        try:
            admin_id = create_first_admin(conn, email, full_name, hash_password(password))
        except AdminAlreadyExists as e:
            print(f"Nothing done: {e}. Create further admins with POST /admin-auth/register.", file=sys.stderr)
            return 1
    finally:
        conn.close()

    print(f"First admin created on '{args.stage}': {email} ({admin_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
