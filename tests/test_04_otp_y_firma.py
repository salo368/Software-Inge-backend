"""E2E: OTP, estampado del PDF con certificado y avance del CDT a pago."""
import hashlib
from io import BytesIO

from conftest import (
    CDTS_API, SIGN_API, api, fetch, fila_proceso, foto_rostro_real,
    imagen_con_texto, otp_de_db, subir_foto,
)

_estado: dict = {}


def _preparar_fotos(proceso):
    if _estado.get("fotos_listas"):
        return
    subir_foto(proceso["token_firma"], "cedula_front", imagen_con_texto(
        ["REPUBLICA DE COLOMBIA", "IDENTIFICACION PERSONAL"]))
    subir_foto(proceso["token_firma"], "cedula_back", imagen_con_texto(
        ["FECHA DE NACIMIENTO", "ESTATURA", "FECHA Y LUGAR DE EXPEDICION"]))
    subir_foto(proceso["token_firma"], "face", foto_rostro_real())
    _estado["fotos_listas"] = True


def test_otp_requiere_firma_dibujada(proceso):
    """Dado un proceso sin firma dibujada, no se puede pedir el OTP (409)."""
    _preparar_fotos(proceso)
    s, r = api(f"{SIGN_API}/signatures/{proceso['token_firma']}/otp", "POST")
    assert s == 409 and r["error"] == "signature_missing"


def test_otp_se_envia_con_firma_dibujada(proceso):
    """Dada la firma dibujada, el OTP se genera y se envia al correo."""
    subir_foto(proceso["token_firma"], "signature", imagen_con_texto(["Firma"]), "image/png")
    s, r = api(f"{SIGN_API}/signatures/{proceso['token_firma']}/otp", "POST")
    assert s == 200 and r["status"] == "sent"


def test_otp_incorrecto_no_firma(proceso):
    """Dado un OTP equivocado, se rechaza con 401 y descuenta un intento."""
    real = otp_de_db(proceso["token_firma"])
    equivocado = f"{(int(real) + 1) % 1_000_000:06d}"
    s, r = api(f"{SIGN_API}/signatures/{proceso['token_firma']}/confirm", "POST", {"otp": equivocado})
    assert s == 401 and r["error"] == "invalid_otp"
    _estado["otp"] = real


def test_otp_correcto_firma_y_avanza_el_cdt(proceso, usuario):
    """Dado el OTP correcto: PDF firmado con certificado y hash, y CDT en pago."""
    s, r = api(f"{SIGN_API}/signatures/{proceso['token_firma']}/confirm", "POST",
               {"otp": _estado["otp"]})
    assert s == 200 and r["status"] == "signed", r

    # PDF: contrato + hoja de certificado con el hash impreso
    from pypdf import PdfReader
    pdf = fetch(r["signed_pdf_url"])
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2
    texto_cert = reader.pages[1].extract_text()
    assert "Certificado de firma digital" in texto_cert
    assert r["doc_hash"] in texto_cert

    # El hash queda persistido para verificacion posterior
    fila = fila_proceso(proceso["token_firma"])
    assert fila["stage"] == "firmado" and fila["doc_hash"] == r["doc_hash"]

    # El CDT avanza a pago con la url del documento firmado
    s, cdt = api(f"{CDTS_API}/cdts/{proceso['cdt_id']}", token=usuario["token"])
    assert s == 200 and cdt["stage"] == "pago"
    assert cdt["signature_url"].startswith("s3://")


def test_proceso_firmado_no_se_repite(proceso):
    """Dado un proceso ya firmado, confirmar de nuevo responde 409."""
    s, r = api(f"{SIGN_API}/signatures/{proceso['token_firma']}/confirm", "POST", {"otp": "000000"})
    assert s == 409 and r["error"] == "already_signed"
