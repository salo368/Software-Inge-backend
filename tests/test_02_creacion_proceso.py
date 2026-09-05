"""E2E: creacion del proceso de firma (contra el ambiente dev desplegado)."""
import random

from conftest import ACCESS_API, SIGN_API, TEST_EMAIL, api, crear_cdt_en_firma

_estado: dict = {}


def test_requiere_autenticacion(e2e):
    """Dado un llamado sin bearer token, se rechaza con 401."""
    s, _ = api(f"{SIGN_API}/signatures", "POST", {"cdt_id": 1, "email": TEST_EMAIL})
    assert s == 401


def test_cdt_debe_estar_en_etapa_firma(usuario):
    """Dado un CDT en formularios, no se puede iniciar la firma (409)."""
    from conftest import CDTS_API
    _, cdt = api(f"{CDTS_API}/cdts", "POST",
                 {"amount": 1_000_000, "term": 90, "rate": 10, "bank": "nu"}, usuario["token"])
    s, r = api(f"{SIGN_API}/signatures", "POST",
               {"cdt_id": cdt["id"], "email": TEST_EMAIL}, usuario["token"])
    assert s == 409 and r["error"] == "cdt_not_in_firma"


def test_cdt_ajeno_no_permitido(usuario):
    """Dado un CDT de otro usuario, se responde 404 como si no existiera."""
    cdt_id = crear_cdt_en_firma(usuario["token"])
    otro = f"tdd_{random.randint(10000, 99999)}"
    api(f"{ACCESS_API}/register", "POST", {"username": otro, "name": "Otro", "password": "test1234"})
    _, login = api(f"{ACCESS_API}/login", "POST", {"username": otro, "password": "test1234"})
    s, r = api(f"{SIGN_API}/signatures", "POST",
               {"cdt_id": cdt_id, "email": TEST_EMAIL}, login["token"])
    assert s == 404 and r["error"] == "cdt_not_found"
    _estado["cdt_id"] = cdt_id


def test_creacion_exitosa_envia_enlace(usuario):
    """Dado un CDT propio en firma, se crea el proceso y el enlace es HTTPS del front de firma."""
    s, r = api(f"{SIGN_API}/signatures", "POST",
               {"cdt_id": _estado["cdt_id"], "email": TEST_EMAIL}, usuario["token"])
    assert s == 201, r
    assert r["sign_url"].startswith("https://") and "/s/" in r["sign_url"]
    assert r["email"] == TEST_EMAIL
    _estado["token_firma"] = r["sign_url"].rsplit("/", 1)[-1]


def test_consulta_enmascara_el_correo(e2e):
    """Dado un proceso creado, la consulta publica enmascara el correo y entrega el PDF."""
    s, p = api(f"{SIGN_API}/signatures/{_estado['token_firma']}")
    assert s == 200
    local, _, dominio = TEST_EMAIL.partition("@")
    assert p["email_masked"] == f"{local[:2]}***@{dominio}"
    assert p["stage"] == "revision"
    assert p["pdf_url"].startswith("https://")
    assert p["uploads"] == {"cedula_front": False, "cedula_back": False, "face": False, "signature": False}


def test_token_invalido_responde_404(e2e):
    """Dado un token que no existe, se responde 404."""
    s, r = api(f"{SIGN_API}/signatures/token-que-no-existe")
    assert s == 404 and r["error"] == "process_not_found"
