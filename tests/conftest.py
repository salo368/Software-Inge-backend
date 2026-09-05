"""Fixtures y helpers para los escenarios de prueba de la firma digital.

- Unitarias: cargan el handler localmente, no requieren AWS.
- E2E: corren contra el ambiente dev desplegado; requieren credenciales
  cargadas (source scripts/load-aws-env.sh) y envian correos reales.
"""
import importlib.util
import json
import os
import random
import sys
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Necesarias para importar handlers en pruebas unitarias (no se usan de verdad)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("FILES_BUCKET", "bucket-de-prueba")
os.environ.setdefault("SIGN_FRONT_URL", "https://firma.test")
os.environ.setdefault("COMMERCE_URL", "http://comercio.test")

ACCESS_API = os.environ.get("ACCESS_API", "https://mzqwooof17.execute-api.us-east-1.amazonaws.com")
CDTS_API = os.environ.get("CDTS_API", "https://0b3y7zzuw9.execute-api.us-east-1.amazonaws.com")
SIGN_API = os.environ.get("SIGN_API", "https://6u8p2z9blf.execute-api.us-east-1.amazonaws.com")
TEST_EMAIL = os.environ.get("TEST_EMAIL", "diskretssrs@gmail.com")

FACE_JPG = Path(__file__).parent / "assets" / "face.jpg"


# ---------- helpers HTTP ----------

def api(url: str, method: str = "GET", body=None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def put_binary(url: str, data: bytes, ctype: str) -> int:
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype}, method="PUT")
    with urllib.request.urlopen(req) as r:
        return r.status


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url) as r:
        return r.read()


# ---------- helpers de imagenes ----------

def imagen_con_texto(lineas: list[str]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1280, 800), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 64)
    y = 120
    for ln in lineas:
        d.text((80, y), ln, fill="black", font=font)
        y += 120
    buf = BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def imagen_en_blanco() -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (1280, 800), "white").save(buf, "JPEG")
    return buf.getvalue()


def foto_rostro_real() -> bytes:
    return FACE_JPG.read_bytes()


# ---------- helpers de flujo ----------

def crear_cdt_en_firma(token: str) -> int:
    _, cdt = api(f"{CDTS_API}/cdts", "POST",
                 {"amount": 1_000_000, "term": 90, "rate": 10, "bank": "nu"}, token)
    api(f"{CDTS_API}/cdts/{cdt['id']}/advance", "POST", token=token)
    api(f"{CDTS_API}/cdts/{cdt['id']}/advance", "POST", token=token)
    return cdt["id"]


def subir_foto(token_firma: str, tipo: str, data: bytes, ctype: str = "image/jpeg"):
    s, up = api(f"{SIGN_API}/signatures/{token_firma}/uploads", "POST",
                {"type": tipo, "content_type": ctype})
    assert s == 200, up
    put_binary(up["upload_url"], data, ctype)


def validar_foto(token_firma: str, tipo: str):
    return api(f"{SIGN_API}/signatures/{token_firma}/validate", "POST", {"type": tipo})


# ---------- acceso a la base (solo E2E) ----------

def conexion_db():
    import boto3
    import pg8000
    ssm = boto3.client("ssm")
    p = {x["Name"].rsplit("/", 1)[-1]: x["Value"]
         for x in ssm.get_parameters_by_path(Path="/cdts/dev/db", WithDecryption=True)["Parameters"]}
    return pg8000.connect(host=p["host"], port=int(p["port"]), database=p["name"],
                          user=p["user"], password=p["password"])


def otp_de_db(token_firma: str) -> str:
    conn = conexion_db()
    cur = conn.cursor()
    cur.execute("SELECT otp_hash FROM digital_signatures WHERE token = %s", (token_firma,))
    h = cur.fetchone()[0].strip()
    conn.close()
    import hashlib
    for i in range(1_000_000):
        if hashlib.sha256(f"{i:06d}".encode()).hexdigest() == h:
            return f"{i:06d}"
    raise RuntimeError("OTP no encontrado")


def fila_proceso(token_firma: str) -> dict:
    conn = conexion_db()
    cur = conn.cursor()
    cur.execute("SELECT stage, doc_hash FROM digital_signatures WHERE token = %s", (token_firma,))
    stage, doc_hash = cur.fetchone()
    conn.close()
    return {"stage": stage, "doc_hash": doc_hash.strip() if doc_hash else None}


# ---------- fixtures ----------

@pytest.fixture(scope="session")
def e2e():
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        pytest.skip("E2E requiere credenciales AWS: source scripts/load-aws-env.sh")


@pytest.fixture(scope="session")
def usuario(e2e):
    username = f"tdd_{random.randint(10000, 99999)}"
    api(f"{ACCESS_API}/register", "POST",
        {"username": username, "name": "TDD Firma", "password": "test1234"})
    _, r = api(f"{ACCESS_API}/login", "POST", {"username": username, "password": "test1234"})
    return {"username": username, "token": r["token"]}


@pytest.fixture(scope="module")
def proceso(usuario):
    """CDT en etapa firma con proceso de firma creado (envia 1 correo real)."""
    cdt_id = crear_cdt_en_firma(usuario["token"])
    s, p = api(f"{SIGN_API}/signatures", "POST",
               {"cdt_id": cdt_id, "email": TEST_EMAIL}, usuario["token"])
    assert s == 201, p
    return {"cdt_id": cdt_id, "token_firma": p["sign_url"].rsplit("/", 1)[-1]}


@pytest.fixture(scope="session")
def validate_handler():
    spec = importlib.util.spec_from_file_location(
        "validate_handler", ROOT / "services/digital_signature/src/validate/handler.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- reporte HTML ----------

def pytest_html_report_title(report):
    report.title = "CDTs — Escenarios de prueba: firma digital"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    report.description = (item.function.__doc__ or "").strip().splitlines()[0] if item.function.__doc__ else ""


def pytest_html_results_table_header(cells):
    cells.insert(2, "<th>Escenario</th>")


def pytest_html_results_table_row(report, cells):
    cells.insert(2, f"<td>{getattr(report, 'description', '')}</td>")
