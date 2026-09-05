"""E2E: validacion de las fotos de identidad con Rekognition (OCR y rostro)."""
from conftest import (
    SIGN_API, api, foto_rostro_real, imagen_con_texto, imagen_en_blanco,
    subir_foto, validar_foto,
)


def test_tipo_de_foto_invalido(proceso):
    """Dado un tipo de archivo desconocido, la subida se rechaza con 400."""
    s, r = api(f"{SIGN_API}/signatures/{proceso['token_firma']}/uploads", "POST",
               {"type": "pasaporte", "content_type": "image/jpeg"})
    assert s == 400 and r["error"] == "invalid_type"


def test_frente_en_blanco_es_rechazado(proceso):
    """Dada una foto sin texto como frente de cedula, la validacion la descarta."""
    subir_foto(proceso["token_firma"], "cedula_front", imagen_en_blanco())
    s, r = validar_foto(proceso["token_firma"], "cedula_front")
    assert s == 200 and r == {"valid": False}
    _, p = api(f"{SIGN_API}/signatures/{proceso['token_firma']}")
    assert p["uploads"]["cedula_front"] is False


def test_frente_con_texto_oficial_es_aceptado(proceso):
    """Dado un frente con los textos oficiales, el OCR la acepta."""
    subir_foto(proceso["token_firma"], "cedula_front", imagen_con_texto(
        ["REPUBLICA DE COLOMBIA", "IDENTIFICACION PERSONAL", "CEDULA DE CIUDADANIA"]))
    s, r = validar_foto(proceso["token_firma"], "cedula_front")
    assert s == 200 and r == {"valid": True}


def test_reverso_con_texto_del_frente_es_rechazado(proceso):
    """Dado un reverso con texto que no corresponde, se descarta."""
    subir_foto(proceso["token_firma"], "cedula_back", imagen_con_texto(["REPUBLICA DE COLOMBIA"]))
    s, r = validar_foto(proceso["token_firma"], "cedula_back")
    assert s == 200 and r == {"valid": False}


def test_reverso_con_campos_oficiales_es_aceptado(proceso):
    """Dado un reverso con los campos del documento, el OCR lo acepta."""
    subir_foto(proceso["token_firma"], "cedula_back", imagen_con_texto(
        ["FECHA DE NACIMIENTO", "LUGAR DE NACIMIENTO", "ESTATURA", "FECHA Y LUGAR DE EXPEDICION"]))
    s, r = validar_foto(proceso["token_firma"], "cedula_back")
    assert s == 200 and r == {"valid": True}


def test_foto_sin_rostro_es_rechazada(proceso):
    """Dada una imagen sin cara como selfie, la deteccion de rostro la descarta."""
    subir_foto(proceso["token_firma"], "face", imagen_en_blanco())
    s, r = validar_foto(proceso["token_firma"], "face")
    assert s == 200 and r == {"valid": False}


def test_rostro_real_es_aceptado_y_avanza_a_dibujo(proceso):
    """Dada una foto con una cara real, se acepta y el proceso avanza a dibujo."""
    subir_foto(proceso["token_firma"], "face", foto_rostro_real())
    s, r = validar_foto(proceso["token_firma"], "face")
    assert s == 200 and r == {"valid": True}
    _, p = api(f"{SIGN_API}/signatures/{proceso['token_firma']}")
    assert p["uploads"] == {"cedula_front": True, "cedula_back": True, "face": True, "signature": False}
    assert p["stage"] == "dibujo"
