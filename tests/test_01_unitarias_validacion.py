"""Unitarias: logica de validacion OCR (sin AWS, corren en local)."""


def test_normaliza_tildes_y_mayusculas(validate_handler):
    """Dado un texto con tildes y minusculas, se normaliza para comparar."""
    assert validate_handler._normalize("Identificación  Personal") == "IDENTIFICACION PERSONAL"
    assert validate_handler._normalize("república de colombia") == "REPUBLICA DE COLOMBIA"


def test_frase_exacta_coincide(validate_handler):
    """Dada una linea OCR identica a la frase esperada, hay coincidencia."""
    assert validate_handler._matches(["REPUBLICA DE COLOMBIA"], "REPUBLICA DE COLOMBIA")


def test_frase_con_errores_de_ocr_coincide(validate_handler):
    """Dado un OCR con errores tipicos (0 por O, 8 por B), igual coincide."""
    assert validate_handler._matches(["REPU8LICA DE C0LOMBIA"], "REPUBLICA DE COLOMBIA")


def test_frase_distinta_no_coincide(validate_handler):
    """Dado un texto de otro documento, no hay coincidencia."""
    assert not validate_handler._matches(["TARJETA DE PROPIEDAD"], "REPUBLICA DE COLOMBIA")


def test_frente_valido_con_dos_de_tres_frases(validate_handler):
    """Dado un frente donde el OCR solo leyo 2 de las 3 frases, se acepta (margen)."""
    lineas = ["REPUBLICA DE COLOMBIA", "IDENTIFICACION PERSONAL"]
    assert validate_handler._score(lineas, validate_handler.FRONT_KEYWORDS) >= validate_handler.FRONT_MIN


def test_frente_invalido_con_una_sola_frase(validate_handler):
    """Dado un frente donde solo se leyo 1 frase, se rechaza."""
    lineas = ["REPUBLICA DE COLOMBIA", "OTRA COSA CUALQUIERA"]
    assert validate_handler._score(lineas, validate_handler.FRONT_KEYWORDS) < validate_handler.FRONT_MIN


def test_reverso_valido_con_tres_de_cinco_campos(validate_handler):
    """Dado un reverso con fecha de nacimiento, estatura y expedicion, se acepta."""
    lineas = ["FECHA DE NACIMIENTO", "ESTATURA 1.75", "FECHA Y LUGAR DE EXPEDICION"]
    assert validate_handler._score(lineas, validate_handler.BACK_KEYWORDS) >= validate_handler.BACK_MIN


def test_reverso_invalido_con_dos_campos(validate_handler):
    """Dado un reverso donde solo se leyeron 2 campos, se rechaza."""
    lineas = ["ESTATURA 1.75", "SEXO M"]
    assert validate_handler._score(lineas, validate_handler.BACK_KEYWORDS) < validate_handler.BACK_MIN
