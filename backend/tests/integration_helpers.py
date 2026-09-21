"""Shared helpers for colocated `integration.py` tests.

These helpers only make sense when running against a *deployed* stage
(currently only `dev`). They:

  * Discover each service's API Gateway base URL from the CloudFormation
    stack outputs (or fall back to `apigatewayv2 get-apis`).
  * Open a real Postgres connection to the stage's schema, using the same
    SSM parameters the Lambdas use at runtime.
  * Provide S3 read helpers, throwaway user creation, and cleanup helpers
    that tests use in `try/finally` to keep dev tidy.

Tests must be marked with `@pytest.mark.integration` so they only run when
pytest is invoked with `--integration` (see backend/conftest.py). This
prevents accidental hits against real infra from a plain local `pytest`.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Iterator

import bcrypt
import boto3
import botocore.config
import pg8000.native
import requests

# ---------------------------------------------------------------------------
# boto3 client factory with fast, bounded retries.
#
# GitHub-hosted runners are NOT EC2 instances, so IMDS (Instance Metadata
# Service) probes just hang for their full timeout budget. We disable IMDS
# via `AWS_EC2_METADATA_DISABLED=true` at the workflow level; here we also
# cap client-side retries so a real failure surfaces in ~15s instead of
# after 5 minutes of exponential backoff.
# ---------------------------------------------------------------------------
_BOTO_CONFIG = botocore.config.Config(
    retries={"max_attempts": 2, "mode": "standard"},
    connect_timeout=5,
    read_timeout=15,
)


def _client(service: str):
    return boto3.client(service, region_name=REGION, config=_BOTO_CONFIG)


# ---------------------------------------------------------------------------
# Env / config
# ---------------------------------------------------------------------------
STAGE = os.environ.get("STAGE", "dev")
REGION = os.environ.get("AWS_REGION", "us-east-1")
SSM_DB_PATH = os.environ.get("SSM_DB_PATH", f"/cdts/{STAGE}/db")

# Emails and other identifiers use this domain so a nightly cleanup job (or
# a manual DELETE) can safely target them without touching real users.
TEST_EMAIL_DOMAIN = "itest.cdts.dev"
TEST_PREFIX = "itest-"


def unique_email() -> str:
    """Returns a fresh email guaranteed not to collide with anything real."""
    return f"{TEST_PREFIX}{uuid.uuid4()}@{TEST_EMAIL_DOMAIN}"


def unique_name(kind: str = "obj") -> str:
    """Returns a unique identifier tagged with the test prefix."""
    return f"{TEST_PREFIX}{kind}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# API Gateway URL discovery
# ---------------------------------------------------------------------------
@lru_cache(maxsize=None)
def api_base(service: str) -> str:
    """Returns the API Gateway HTTP API base URL for `cdts-<STAGE>-<service>`.

    Prefers the CFN stack output `HttpApiUrl` (which Serverless Framework
    creates automatically for `provider.httpApi` services). Falls back to
    scanning `apigatewayv2 get-apis` by name.

    Raises RuntimeError if neither works, so a broken discovery loudly fails
    the integration job rather than silently hitting the wrong host.
    """
    stack_name = f"cdts-{STAGE}-{service}"
    cfn = _client("cloudformation")
    try:
        resp = cfn.describe_stacks(StackName=stack_name)
        outputs = resp["Stacks"][0].get("Outputs", []) or []
        for o in outputs:
            if o["OutputKey"] == "HttpApiUrl":
                return o["OutputValue"].rstrip("/")
    except cfn.exceptions.ClientError:
        # Stack may not exist yet, or credentials may lack cfn:DescribeStacks.
        pass

    # Fallback: enumerate HTTP APIs and match by conventional name. Serverless
    # names the HttpApi resource `${sls:stage}-${service}` by default.
    #
    # Belt-and-suspenders: cap the pagination loop at 20 pages so a broken
    # response (e.g. a MagicMock stub returning a truthy MagicMock for
    # NextToken forever) fails loudly instead of hanging the runner. The
    # real AWS account has O(10) HTTP APIs -- 20 pages of 500 is way more
    # than enough.
    apigw = _client("apigatewayv2")
    candidate_names = {
        f"{STAGE}-{service}",
        f"cdts-{STAGE}-{service}",
        stack_name,
    }
    token = None
    for _ in range(20):
        kwargs: dict[str, Any] = {"MaxResults": "500"}
        if token:
            kwargs["NextToken"] = token
        page = apigw.get_apis(**kwargs)
        items = page.get("Items", []) or []
        if not isinstance(items, list):
            raise RuntimeError(
                f"apigatewayv2.get_apis returned a non-list Items ({type(items).__name__}); "
                f"is boto3 stubbed by conftest.py? See conftest.py step 3."
            )
        for api in items:
            if api.get("Name") in candidate_names:
                return api["ApiEndpoint"].rstrip("/")
        token = page.get("NextToken")
        if not token or not isinstance(token, str):
            break

    raise RuntimeError(
        f"could not resolve API base URL for service '{service}' in stage "
        f"'{STAGE}'; add an Outputs.HttpApiUrl to its serverless.yml or "
        f"check that the stack '{stack_name}' has been deployed."
    )


# ---------------------------------------------------------------------------
# Postgres access
# ---------------------------------------------------------------------------
_REQUIRED_DB_KEYS = ("host", "port", "name", "user", "password")


@lru_cache(maxsize=1)
def _load_db_config() -> dict[str, str]:
    """Reads the DB config for the current stage from SSM.

    Mirrors the exact call shape libs/core/db.py uses at runtime (no
    trailing slash on Path) but adds pagination + explicit key validation
    so a partial response fails with a useful error instead of an opaque
    KeyError('host') downstream in db_conn()."""
    ssm = _client("ssm")
    out: dict[str, str] = {}
    token: str | None = None
    for _ in range(5):  # 5 pages of MaxResults=10 == 50 params, way over budget.
        kwargs: dict[str, Any] = {
            "Path": SSM_DB_PATH.rstrip("/"),
            "WithDecryption": True,
        }
        if token:
            kwargs["NextToken"] = token
        resp = ssm.get_parameters_by_path(**kwargs)
        for p in resp.get("Parameters", []) or []:
            out[p["Name"].rsplit("/", 1)[-1]] = p["Value"]
        token = resp.get("NextToken")
        if not token:
            break

    missing = [k for k in _REQUIRED_DB_KEYS if k not in out]
    if missing:
        raise RuntimeError(
            f"SSM path {SSM_DB_PATH!r} returned {sorted(out.keys())!r} but "
            f"integration tests need {list(_REQUIRED_DB_KEYS)!r}. Missing: "
            f"{missing!r}. Check IAM (ssm:GetParametersByPath on that path) "
            f"and that the params actually exist in the target account."
        )
    return out


@contextmanager
def db_conn() -> Iterator[pg8000.native.Connection]:
    """Opens a Postgres connection with `search_path` set to the stage schema.

    Use as `with db_conn() as c: c.run("SELECT ...")`. Rolls back and closes
    on exit.

    NOTE: `ssl_context` is intentionally None (the default) to mirror what
    `libs/core/db.py` uses at runtime. Passing `ssl_context=True` when the
    RDS server does not require SSL causes pg8000 to hang on the TLS
    handshake instead of falling back cleanly."""
    cfg = _load_db_config()
    conn = pg8000.native.Connection(
        host=cfg["host"],
        port=int(cfg["port"]),
        database=cfg["name"],
        user=cfg["user"],
        password=cfg["password"],
        timeout=15,
    )
    try:
        conn.run(f'SET search_path TO "{cfg.get("schema", STAGE)}", pg_catalog')
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def query_one(sql: str, **params) -> dict[str, Any] | None:
    """Returns the first row of a parameterized query as a dict, or None."""
    with db_conn() as c:
        rows = c.run(sql, **params)
        if not rows:
            return None
        cols = [d["name"] for d in c.columns]
        return dict(zip(cols, rows[0]))


def query_scalar(sql: str, **params) -> Any:
    """Returns the first column of the first row, or None."""
    row = query_one(sql, **params)
    if row is None:
        return None
    return next(iter(row.values()))


def execute(sql: str, **params) -> None:
    """Runs a mutation and returns nothing. Used by cleanup helpers."""
    with db_conn() as c:
        c.run(sql, **params)


# ---------------------------------------------------------------------------
# S3 access
# ---------------------------------------------------------------------------
def _s3():
    return _client("s3")


def s3_head(bucket: str, key: str) -> dict | None:
    """Returns S3 HeadObject metadata for `key`, or None if not present."""
    try:
        return _s3().head_object(Bucket=bucket, Key=key)
    except _s3().exceptions.ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def s3_delete(bucket: str, key: str) -> None:
    try:
        _s3().delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass  # best-effort cleanup


def wait_for(condition, timeout_s: float = 20.0, interval_s: float = 1.0):
    """Polls `condition()` until truthy or timeout. Returns the last value."""
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = condition()
        if last:
            return last
        time.sleep(interval_s)
    return last


# ---------------------------------------------------------------------------
# High-level HTTP helpers
# ---------------------------------------------------------------------------
def signup_and_login(*, full_name: str = "Integration Bot") -> dict:
    """Creates a throwaway user via /auth/register and returns
    {email, password, user_id, token}. The caller MUST clean up the user in
    a finally block via `cleanup_user(email)`.

    Use this ONLY inside auth's own integration.py -- it exercises the
    /auth/register endpoint, which by definition belongs to the auth block.
    Any OTHER block that needs a bearer token to test its own endpoints
    MUST use `create_test_user_directly()` below: crossing block boundaries
    from an integration test defeats the point of per-block packaging
    (see docs/repo-structure.md §13.3)."""
    email = unique_email()
    password = "hunter22aa"
    base = api_base("auth")
    resp = requests.post(
        f"{base}/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    return {
        "email": email,
        "password": password,
        "user_id": body["user"]["id"],
        "token": body["token"],
    }


def create_test_user_directly(*, full_name: str = "Integration Bot") -> dict:
    """Inserts a throwaway user + bearer_token row DIRECTLY in Postgres,
    without touching /auth/register. Returns {email, user_id, token}.

    This is what non-auth blocks (files, processes, signatures, forms)
    should use when they need an authenticated caller to test their own
    endpoints. Bypassing /auth/register keeps the integration for block X
    from silently depending on block Y being freshly deployed in the same
    pipeline run.

    The token is generated + hashed the same way `libs.utils.auth.issue_token`
    does at runtime (secrets.token_urlsafe -> sha256 -> stored hash), so
    the value we return in `token` is a real, working bearer that
    `require_auth` will accept.

    Caller MUST clean up in finally via `cleanup_user(email)`."""
    email = unique_email()
    user_id = uuid.uuid4()
    # bcrypt-hashed placeholder; the tests never log in, they just present
    # the pre-issued bearer directly.
    pw_hash = bcrypt.hashpw(b"unused-for-direct-users", bcrypt.gensalt(4)).decode()
    plain_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plain_token.encode()).hexdigest()
    token_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=1)

    with db_conn() as c:
        c.run(
            "INSERT INTO users (id, email, password_hash, full_name, created_at) "
            "VALUES (:id, :email, :ph, :name, :now)",
            id=user_id, email=email, ph=pw_hash, name=full_name, now=now,
        )
        c.run(
            "INSERT INTO bearer_tokens (id, user_id, token_hash, expires_at, created_at) "
            "VALUES (:tid, :uid, :th, :exp, :now)",
            tid=token_id, uid=user_id, th=token_hash, exp=expires_at, now=now,
        )
    return {"email": email, "user_id": str(user_id), "token": plain_token}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Cleanup helpers (best-effort; safe to call even when the row is missing)
# ---------------------------------------------------------------------------
def cleanup_user(email: str) -> None:
    """Deletes a user and their cascading rows by email. Best-effort."""
    if not email or not email.startswith(TEST_PREFIX):
        # Safety guard: never delete anything that isn't obviously test data.
        return
    with db_conn() as c:
        rows = c.run("SELECT id FROM users WHERE email = :e", e=email)
        if not rows:
            return
        uid = rows[0][0]
        # Order matters: children first. Everything with a FK to users.id.
        for table in ("bearer_tokens", "forms", "processes"):
            try:
                c.run(f"DELETE FROM {table} WHERE user_id = :u", u=uid)
            except Exception:
                pass
        try:
            c.run("DELETE FROM users WHERE id = :u", u=uid)
        except Exception:
            pass


def cleanup_process(process_id: str) -> None:
    """Deletes a process and its dependent files/signatures rows.

    Notes on the v2 signatures schema:
      * The `signatures` table (post Fase 2 destructive migration) is
        decoupled from `processes` and does NOT have a `process_id`
        column. The link is `processes.sign_id -> signatures.sign_id`.
      * Cleanup order therefore: read sign_id off the process row,
        delete files (FK -> process), delete the process, THEN delete
        the ceremony (nothing FKs to it, but we do it last so a
        transient failure leaves the ceremony reachable via the
        process row for diagnostics rather than orphaning it).
    """
    if not process_id:
        return
    with db_conn() as c:
        sign_id: str | None = None
        try:
            rows = c.run(
                "SELECT sign_id FROM processes WHERE id = :p", p=process_id
            )
            if rows and rows[0][0]:
                sign_id = rows[0][0]
        except Exception:
            pass
        try:
            c.run("DELETE FROM files WHERE process_id = :p", p=process_id)
        except Exception:
            pass
        try:
            c.run("DELETE FROM processes WHERE id = :p", p=process_id)
        except Exception:
            pass
        if sign_id:
            try:
                c.run(
                    "DELETE FROM signatures WHERE sign_id = :s", s=sign_id
                )
            except Exception:
                pass


def cleanup_signature(sign_id: str) -> None:
    """Deletes a signature ceremony row and the S3 prefix under
    `transactions/{sign_id}/`. Safe to call even if the row or objects
    are missing (best-effort).

    Only clears data the integration test itself created; the row's
    `sign_id` is only known to callers that opened the ceremony in
    this run, so there is no way to accidentally purge real ceremonies.
    """
    if not sign_id:
        return
    with db_conn() as c:
        try:
            c.run("DELETE FROM signatures WHERE sign_id = :s", s=sign_id)
        except Exception:
            pass
    bucket = os.environ.get(
        "SIGNATURES_BUCKET", f"cdts-{STAGE}-signatures"
    )
    cleanup_s3_prefix(bucket, f"transactions/{sign_id}/")


def cleanup_s3_prefix(bucket: str, prefix: str) -> None:
    """Removes every object under a given prefix. Used for signature/process
    subtrees created by an integration test."""
    if not prefix:
        return
    s3 = _s3()
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        objs = page.get("Contents", []) or []
        if objs:
            s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": o["Key"]} for o in objs]},
            )
        token = page.get("NextContinuationToken")
        if not token:
            break
