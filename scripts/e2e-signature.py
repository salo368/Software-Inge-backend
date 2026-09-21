#!/usr/bin/env python3
"""
scripts/e2e-signature.py

End-to-end smoke test of the signatures v2 ceremony against the live
dev environment. Simulates a full user flow:

    1. Register a fresh user (fresh email per run).
    2. POST /forms/me (KYC snapshot).
    3. POST /processes (CDT investment) + advance form -> documents.
    4. get_upload_url + PUT declaracion_renta PDF to files bucket.
    5. advance documents -> signature: `processes.advance` invokes
       `signatures.create` via the bridge; response carries sign_url.
    6. As the signer (using sign_id extracted from sign_url):
         upload_url + PUT for id_front, id_back, face, signature
         validate_id_front, validate_id_back, validate_face
         register_signature
         consent
         request_otp    <-- email goes out
         (interactive)  <-- YOU paste the OTP from your inbox
         verify_otp     <-- triggers async `sign` worker
         poll GET /signatures/{sign_id} until stage=signed
    7. POST /signatures/verify {sign_id: ...} and print the result.
    8. Print the S3 keys of signed.pdf + evidence-package.json.

Requirements on the machine:

    * Python 3.11+
    * pip install requests pillow reportlab boto3
    * A real face photo file (jpg/png) with ONE clear face, eyes open.
      Any snapshot works; Rekognition rejects synthetic drawings.
      Pass with --face /path/to/photo.jpg

Requirements on AWS:

    * scripts/bootstrap-signatures-v2.sh already ran for the stage.
    * AWS credentials in env (AWS_ACCESS_KEY_ID/SECRET) only used for
      CloudFormation URL discovery + final S3 sanity check. HTTP calls
      to the APIs use no AWS auth (public API Gateway + bearer JWT).

Usage:

    export AWS_ACCESS_KEY_ID=...
    export AWS_SECRET_ACCESS_KEY=...
    export AWS_DEFAULT_REGION=us-east-1
    python scripts/e2e-signature.py \\
        --stage dev \\
        --email your@real.email \\
        --face  /path/to/your-selfie.jpg
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import random
import string
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Deps that we NEED. Fail fast with a clear message if missing.
# --------------------------------------------------------------------------- #
try:
    import requests
except ImportError:
    sys.exit("missing dependency: pip install requests")

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("missing dependency: pip install pillow")

try:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas as rl_canvas
except ImportError:
    sys.exit("missing dependency: pip install reportlab")

try:
    import boto3
except ImportError:
    sys.exit("missing dependency: pip install boto3")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--stage", default="dev", choices=["dev", "pro"])
    p.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    p.add_argument(
        "--email",
        required=True,
        help="Real email you can read (the OTP is delivered here).",
    )
    p.add_argument(
        "--face",
        required=True,
        type=Path,
        help="Path to a jpg/png of a real face (one person, eyes open).",
    )
    p.add_argument(
        "--password",
        default="E2eTest!2026",
        help="Password to register with. Default is fine.",
    )
    p.add_argument(
        "--bank-index",
        type=int,
        default=0,
        help="Index into GET /banks to pick which bank to use. Default 0.",
    )
    p.add_argument(
        "--otp-file",
        type=Path,
        default=None,
        help=(
            "If set, wait for the OTP to appear as the first line of "
            "this file (polled every 2s) instead of blocking on stdin. "
            "Useful when driving the script from a non-interactive "
            "shell -- create the file with the OTP AFTER the request_otp "
            "step prints. File is deleted after reading."
        ),
    )
    return p.parse_args()


# --------------------------------------------------------------------------- #
# CloudFormation-based API URL discovery
# --------------------------------------------------------------------------- #
def discover_api_urls(stage: str, region: str) -> dict[str, str]:
    """Reads HttpApiUrl from each cdts-{stage}-<service> stack."""
    cfn = boto3.client("cloudformation", region_name=region)
    services = ["auth", "banks", "files", "forms", "processes", "signatures"]
    urls = {}
    for svc in services:
        stack = f"cdts-{stage}-{svc}"
        resp = cfn.describe_stacks(StackName=stack)
        outputs = resp["Stacks"][0].get("Outputs", [])
        url = next(
            (o["OutputValue"] for o in outputs if o["OutputKey"] == "HttpApiUrl"),
            None,
        )
        if not url:
            api_id = next(
                (o["OutputValue"] for o in outputs if o["OutputKey"] == "HttpApiId"),
                None,
            )
            if not api_id:
                sys.exit(f"stack {stack} has no HttpApiUrl/HttpApiId output")
            url = f"https://{api_id}.execute-api.{region}.amazonaws.com"
        urls[svc] = url.rstrip("/")
    return urls


# --------------------------------------------------------------------------- #
# Synthetic asset generation
# --------------------------------------------------------------------------- #
def make_investment_order_pdf() -> bytes:
    """A minimal single-page PDF the user uploads as 'declaracion_renta'."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 720, "DECLARACION DE RENTA - E2E TEST")
    c.setFont("Helvetica", 10)
    c.drawString(72, 690, f"Generated at {datetime.now(timezone.utc).isoformat()}")
    c.drawString(
        72,
        670,
        "This is a synthetic PDF produced by scripts/e2e-signature.py.",
    )
    c.showPage()
    c.save()
    return buf.getvalue()


def make_id_document_png(side: str = "front") -> bytes:
    """A PNG that looks like an ID card front/back. Contains enough
    printed text (>= 3 lines) with a numeric block (>= 6 digits) so
    Rekognition DetectText clears the heuristics."""
    W, H = 640, 400
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (W - 1, H - 1)], outline="black", width=4)

    # Try to load a real font; fall back to default bitmap otherwise.
    try:
        font_lg = ImageFont.truetype("arial.ttf", 32)
        font_md = ImageFont.truetype("arial.ttf", 22)
        font_sm = ImageFont.truetype("arial.ttf", 18)
    except (OSError, IOError):
        font_lg = ImageFont.load_default()
        font_md = ImageFont.load_default()
        font_sm = ImageFont.load_default()

    if side == "front":
        lines = [
            ("REPUBLIC OF EXAMPLE", font_lg, 30),
            ("IDENTITY DOCUMENT", font_md, 80),
            ("Number: 1.234.567.890", font_md, 130),
            ("Name: JANE DOE E2E", font_md, 180),
            ("Born: 15/01/1990   Sex: F", font_sm, 230),
            ("Issued: 2024-06-10", font_sm, 265),
        ]
    else:
        lines = [
            ("BACK OF IDENTITY DOCUMENT", font_lg, 30),
            ("Place of birth: EXAMPLE CITY", font_md, 90),
            ("Height: 165 cm  Blood: O+", font_md, 140),
            ("Signature: [placeholder]", font_sm, 200),
            ("Address: 123 EXAMPLE ST", font_sm, 240),
        ]
    for text, font, y in lines:
        draw.text((30, y), text, fill="black", font=font)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def make_signature_png() -> bytes:
    """Transparent PNG with a squiggly line resembling a signature."""
    W, H = 600, 200
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Deterministic pseudo-signature: sinusoidal path with jitter.
    rng = random.Random(42)
    points = []
    for x in range(20, W - 20, 4):
        y = int(100 + 30 * (rng.random() - 0.5) + 15 * ((x % 60) - 30) / 30)
        points.append((x, y))
    draw.line(points, fill=(20, 20, 90, 255), width=4)
    # A small flourish at the end.
    draw.line(
        [(W - 40, 100), (W - 20, 80), (W - 60, 90), (W - 20, 130)],
        fill=(20, 20, 90, 255),
        width=4,
    )
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _random_suffix(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _post(url: str, *, headers: dict | None = None, json_body: dict | None = None,
          timeout: int = 30):
    r = requests.post(url, json=json_body, headers=headers, timeout=timeout)
    return r


def _get(url: str, *, headers: dict | None = None, timeout: int = 30):
    r = requests.get(url, headers=headers, timeout=timeout)
    return r


def _die_on_bad(resp: requests.Response, step: str) -> dict:
    if not (200 <= resp.status_code < 300):
        print(f"\n[FAIL] {step}: HTTP {resp.status_code}")
        print(f"       body: {resp.text[:600]}")
        sys.exit(1)
    try:
        return resp.json()
    except ValueError:
        print(f"[FAIL] {step}: response was not JSON: {resp.text[:200]}")
        sys.exit(1)


def _step(msg: str) -> None:
    print(f"\n=> {msg}")


# --------------------------------------------------------------------------- #
# S3 upload via presigned URL
# --------------------------------------------------------------------------- #
def _put_to_presigned(url: str, body: bytes, content_type: str,
                      extra_headers: dict | None = None) -> None:
    headers = {"Content-Type": content_type}
    if extra_headers:
        headers.update(extra_headers)
    r = requests.put(url, data=body, headers=headers, timeout=60)
    if not (200 <= r.status_code < 300):
        print(f"[FAIL] S3 PUT: HTTP {r.status_code}\n{r.text[:400]}")
        sys.exit(1)


# --------------------------------------------------------------------------- #
# Main flow
# --------------------------------------------------------------------------- #
def main() -> None:
    args = _parse_args()

    if not args.face.is_file():
        sys.exit(f"face file not found: {args.face}")

    face_bytes = args.face.read_bytes()
    face_ct = "image/png" if args.face.suffix.lower() == ".png" else "image/jpeg"

    _step("Discovering API URLs from CloudFormation")
    urls = discover_api_urls(args.stage, args.region)
    for k, v in urls.items():
        print(f"    {k:11s} -> {v}")

    # Fresh email per run: unique local-part so re-runs don't collide
    # with the auth 'email_taken' guard. We use the tag+ suffix so the
    # OTP still lands in the same inbox.
    suffix = _random_suffix()
    if "+" in args.email:
        base, tag = args.email.split("+", 1)
        register_email = f"{base}+e2e-{suffix}@{tag.split('@',1)[1]}"
    else:
        local, domain = args.email.split("@", 1)
        register_email = f"{local}+e2e-{suffix}@{domain}"
    print(f"\nWill register a fresh user: {register_email}")
    print(f"OTPs will be delivered to that address (tag+ collapses to your inbox).")

    # 1) Register (auto-issues bearer token).
    _step("Registering fresh user")
    reg = _post(
        f"{urls['auth']}/auth/register",
        json_body={
            "email": register_email,
            "password": args.password,
            "full_name": "E2E Signer",
        },
    )
    reg_body = _die_on_bad(reg, "auth/register")
    token = reg_body["token"]
    print(f"    user_id: {reg_body['user']['id']}")
    print(f"    token:   {token[:16]}...")
    auth = {"Authorization": f"Bearer {token}"}

    # 2) Upsert form (KYC snapshot).
    _step("Upserting form (KYC snapshot)")
    form_body = {
        "full_name": "E2E Signer",
        "birth_date": "1990-01-15",
        "document_type": "CC",
        "document_number": "1234567890",
        "phone": "+57 3001234567",
        "address": "123 Example St",
        "city": "Bogota",
        "occupation": "Software Engineer",
        "economic_activity": "IT services",
        "source_of_funds": "Salary",
        "monthly_income": 8000000,
        "monthly_expenses": 3000000,
        "total_assets": 50000000,
        "total_liabilities": 10000000,
        "is_peps": False,
    }
    _die_on_bad(
        requests.put(f"{urls['forms']}/forms/me", json=form_body, headers=auth, timeout=30),
        "forms/me PUT",
    )

    # 3) Pick a bank + create process.
    _step("Listing banks and creating process")
    banks_resp = _die_on_bad(_get(f"{urls['banks']}/banks", headers=auth), "banks/list")
    banks = banks_resp.get("banks") or banks_resp
    active_banks = [b for b in banks if b.get("is_active", True)]
    if not active_banks:
        sys.exit("no active banks in db")
    bank = active_banks[args.bank_index % len(active_banks)]
    print(f"    picked bank: {bank['id']} - {bank['name']}")

    proc_body = _die_on_bad(
        _post(
            f"{urls['processes']}/processes",
            headers=auth,
            json_body={
                "bank_id": bank["id"],
                "amount": 5000000,
                "term_days": 180,
                "rate": 12.5,
            },
        ),
        "processes/create",
    )
    proc = proc_body["process"]
    pid = proc["id"]
    print(f"    process_id: {pid}   stage: {proc['stage']}")

    # 4) Advance form -> documents.
    _step("Advancing form -> documents")
    adv1 = _die_on_bad(
        _post(f"{urls['processes']}/processes/{pid}/advance", headers=auth, json_body={}),
        "advance #1",
    )
    print(f"    stage now: {adv1['process']['stage']}")

    # 5) Upload declaracion_renta.
    _step("Requesting upload URL for declaracion_renta")
    ul = _die_on_bad(
        _post(
            f"{urls['files']}/files/upload-url",
            headers=auth,
            json_body={
                "process_id": pid,
                "file_type": "declaracion_renta",
                "content_type": "application/pdf",
                "original_name": "declaracion.pdf",
            },
        ),
        "files/upload-url",
    )
    print(f"    key: {ul['key']}")
    _put_to_presigned(ul["upload_url"], make_investment_order_pdf(),
                      "application/pdf", ul.get("upload_headers"))

    # The S3 ObjectCreated event fires the `files/on_upload` worker
    # which registers the row asynchronously. Poll `GET /processes/{id}`
    # until the file appears so we don't race with the worker.
    _step("Waiting for on_upload worker to register the file")
    deadline = time.time() + 30
    while time.time() < deadline:
        p = _die_on_bad(_get(f"{urls['processes']}/processes/{pid}", headers=auth),
                        "processes/get")
        # `files` is a top-level field on the response (not nested
        # under `process`) -- see processes/get/handler.py.
        files = p.get("files") or []
        if any(f["file_type"] == "declaracion_renta" for f in files):
            print(f"    file registered ({len(files)} total)")
            break
        time.sleep(1.5)
    else:
        sys.exit("timeout waiting for on_upload worker")

    # 6) Advance documents -> signature (opens ceremony!).
    _step("Advancing documents -> signature (opens ceremony)")
    adv2 = _die_on_bad(
        _post(f"{urls['processes']}/processes/{pid}/advance", headers=auth, json_body={}),
        "advance #2",
    )
    sign_url = adv2.get("sign_url")
    if not sign_url:
        sys.exit(f"advance #2 did not return sign_url: {adv2}")
    print(f"    sign_url: {sign_url}")

    # Extract sign_id from sign_url. Convention: `${frontend}/#/firmar/${sign_id}`
    # but we defend against schema variation.
    if "/" in sign_url:
        sign_id = sign_url.rstrip("/").split("/")[-1]
    else:
        sign_id = sign_url
    print(f"    sign_id:  {sign_id[:16]}...")

    # --------------------------------------------------------------------- #
    # SIGNER PERSPECTIVE from here on. Auth = sign_id in path only.
    # --------------------------------------------------------------------- #
    _step("Fetching ceremony state as signer (GET /signatures/{sign_id})")
    sig_get_url = f"{urls['signatures']}/signatures/{sign_id}"
    cer = _die_on_bad(_get(sig_get_url), "signatures/get")
    print(f"    stage: {cer['stage']}   signer: {cer['signer_email']}")

    def _upload_evidence(evidence_type: str, body: bytes, content_type: str) -> str:
        """upload_url + PUT + return the S3 key so we can echo it later."""
        ul = _die_on_bad(
            _post(
                f"{urls['signatures']}/signatures/{sign_id}/upload-url",
                json_body={"evidence_type": evidence_type, "content_type": content_type},
            ),
            f"upload-url {evidence_type}",
        )
        _put_to_presigned(ul["upload_url"], body, content_type)
        return ul["key"]

    _step("Uploading ID front, ID back, face, signature drawing")
    _upload_evidence("id_front",          make_id_document_png("front"), "image/png")
    _upload_evidence("id_back",           make_id_document_png("back"),  "image/png")
    _upload_evidence("face",              face_bytes,                    face_ct)
    # upload_url exposes 'signature_drawing' externally (descriptive
    # name for the microfrontend); the ORM and validators map it to
    # 'signature' internally. See _EVIDENCE_MAP in upload_url/handler.py.
    _upload_evidence("signature_drawing", make_signature_png(),          "image/png")

    _step("Validating id_front via Rekognition")
    r = _die_on_bad(
        _post(f"{urls['signatures']}/signatures/{sign_id}/evidence/id-front"),
        "validate_id_front",
    )
    print(f"    lines detected: {r.get('detected_lines')}   stage: {r.get('stage')}")

    _step("Validating id_back via Rekognition")
    r = _die_on_bad(
        _post(f"{urls['signatures']}/signatures/{sign_id}/evidence/id-back"),
        "validate_id_back",
    )
    print(f"    lines detected: {r.get('detected_lines')}   stage: {r.get('stage')}")

    _step("Validating face via Rekognition (this is where synthetic images fail)")
    r = _die_on_bad(
        _post(f"{urls['signatures']}/signatures/{sign_id}/evidence/face"),
        "validate_face",
    )
    print(f"    stage: {r.get('stage')}")

    _step("Registering signature drawing")
    _die_on_bad(
        _post(f"{urls['signatures']}/signatures/{sign_id}/evidence/signature"),
        "register_signature",
    )

    _step("Recording consent")
    r = _die_on_bad(
        _post(
            f"{urls['signatures']}/signatures/{sign_id}/consent",
            json_body={"terms_version": "v1"},
        ),
        "consent",
    )
    print(f"    stage: {r.get('stage')}")

    _step("Requesting OTP (email being sent NOW)")
    r = _die_on_bad(
        _post(f"{urls['signatures']}/signatures/{sign_id}/otp"),
        "request_otp",
    )
    print(f"    stage: {r.get('stage')}")
    print(f"    check your inbox at {register_email}")

    # OTP entry: either interactive stdin OR polling a file. The file
    # mode lets us run the script from a non-interactive shell (create
    # the ceremony, wait for the email, then drop the OTP into the file
    # for the script to pick up).
    if args.otp_file:
        print(f"\n>>> waiting for OTP in {args.otp_file} (polling every 2s)...")
        print(f"    once your email arrives:  echo <OTP> > {args.otp_file}")
        deadline_otp = time.time() + 600  # 10 minutes; OTP validity is much shorter
        otp = ""
        while time.time() < deadline_otp:
            if args.otp_file.is_file():
                raw = args.otp_file.read_text().strip()
                if raw:
                    otp = raw.splitlines()[0].strip()
                    args.otp_file.unlink()  # single-use
                    print(f"    -> got OTP ({len(otp)} chars)")
                    break
            time.sleep(2)
        if not otp:
            sys.exit("timeout waiting for OTP file")
    else:
        otp = input("\n>>> paste the OTP code from your email: ").strip()
        if not otp:
            sys.exit("no OTP entered, aborting")

    _step("Verifying OTP -> triggers async `sign` worker")
    r = _die_on_bad(
        _post(
            f"{urls['signatures']}/signatures/{sign_id}/otp/verify",
            json_body={"code": otp},
        ),
        "verify_otp",
    )
    print(f"    stage after verify: {r.get('stage')}")

    _step("Polling for stage='signed' (sign worker runs async)")
    deadline = time.time() + 120
    last_stage = None
    while time.time() < deadline:
        cer = _die_on_bad(_get(sig_get_url), "signatures/get poll")
        stage = cer["stage"]
        if stage != last_stage:
            print(f"    -> {stage}")
            last_stage = stage
        if stage == "signed":
            break
        if stage in ("failed", "expired"):
            sys.exit(f"ceremony ended in stage={stage} :(")
        time.sleep(2)
    else:
        sys.exit("timeout waiting for stage=signed")

    _step("Verifying the signed PDF via public /signatures/verify")
    v = _die_on_bad(
        _post(
            f"{urls['signatures']}/signatures/verify",
            json_body={"sign_id": sign_id},
        ),
        "verify",
    )
    print(f"    valid:               {v.get('valid')}")
    print(f"    document_integrity:  {v.get('document_integrity')}")
    print(f"    signature_valid:     {v.get('signature_valid')}")
    print(f"    certificate_valid:   {v.get('certificate_valid')}")
    print(f"    cert_serial:         {v.get('cert_serial')}")
    print(f"    signed_at:           {v.get('signed_at')}")
    print(f"    signer.email_masked: {(v.get('signer') or {}).get('email_masked')}")
    if v.get("ceremony"):
        print(f"    ceremony.service_caller: {v['ceremony'].get('service_caller')}")

    _step("S3 sanity check: signed.pdf + evidence-package.json")
    bucket = f"cdts-{args.stage}-signatures"
    s3 = boto3.client("s3", region_name=args.region)
    for suffix in ("signed.pdf", "evidence-package.json"):
        key = f"transactions/{sign_id}/{suffix}"
        try:
            head = s3.head_object(Bucket=bucket, Key=key)
            print(f"    {key}  {head['ContentLength']:>8} bytes  {head['ContentType']}")
        except s3.exceptions.ClientError as e:
            print(f"    {key}  MISSING ({e.response['Error']['Code']})")

    print("\nAll done. Ceremony sign_id:", sign_id)
    print("Process id:", pid, "  now waiting to advance from 'signature' -> 'payment'.")


if __name__ == "__main__":
    main()
