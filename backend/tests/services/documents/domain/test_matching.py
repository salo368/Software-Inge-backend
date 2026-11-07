"""Unit tests for `services/documents/domain/matching.py`.

Cross-cutting porque el módulo es block-local a `documents` pero no está
colocalizado con ningún `handler.py` (mismo patrón que
`tests/services/banks/domain/test_simulacion.py` y
`tests/services/signatures/utils/test_mock_ca.py`): import bare vía
sys.path, sin pasar por `load_handler`.

Datos de OCR 100% sintéticos y deterministas -- no se usa Tesseract real en
estas pruebas (no está instalado en todos los entornos de desarrollo; el
dominio no depende de él, solo el adaptador en `domain/adapters/`, que se
prueba por separado). Cada test documenta explícitamente, en su nombre y en
su docstring, qué hallazgo real del prototipo (`exposicion_C11_
recopilar_documentacion.txt`, sección 7) está fijando.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[4]
_DOCUMENTS_SERVICE = _BACKEND / "services" / "documents"
sys.path.insert(0, str(_DOCUMENTS_SERVICE))

for _n in list(sys.modules):
    if _n == "domain" or _n.startswith("domain."):
        sys.modules.pop(_n, None)

from domain import matching  # noqa: E402 -- explicit sys.path setup above
from domain.ports import ExtractedFields, ExtractedWord  # noqa: E402


def _word(text: str, confidence: float, block: int = 1, par: int = 1, line: int = 1) -> ExtractedWord:
    return ExtractedWord(text=text, confidence=confidence, block_num=block, par_num=par, line_num=line)


def _fields(*words: ExtractedWord) -> ExtractedFields:
    return ExtractedFields(words=tuple(words))


# ---------------------------------------------------------------------------
# evaluar_legibilidad
# ---------------------------------------------------------------------------
class TestEvaluarLegibilidad:
    def test_legible_cuando_hay_suficientes_palabras_con_confianza(self):
        fields = _fields(
            _word("JUAN", 92.0), _word("PEREZ", 90.0), _word("GOMEZ", 88.0),
            _word("1234567890", 95.0), _word("BOGOTA", 85.0),
        )
        result = matching.evaluar_legibilidad(fields)
        assert result.legible is True

    def test_ilegible_cuando_hay_menos_de_5_palabras_detectadas(self):
        """FE1: el umbral es sobre CANTIDAD de palabras con texto real, no
        solo sobre confianza promedio -- un documento casi en blanco con 2
        palabras de alta confianza no debe pasar."""
        fields = _fields(_word("X", 99.0), _word("Y", 99.0))
        result = matching.evaluar_legibilidad(fields)
        assert result.legible is False
        assert result.reason == "documento_ilegible"

    def test_confianza_no_se_promedia_sobre_entradas_sin_texto(self):
        """Hallazgo 2 del prototipo: una imagen de puro ruido daba 95% de
        confianza promedio porque Tesseract reporta entradas estructurales
        (confianza alta) sin texto asociado. Fix: promediar solo palabras
        con `text.strip()` no vacío."""
        fields = _fields(
            # Entradas "estructurales" de alta confianza pero sin texto real.
            _word("", 97.0), _word("   ", 96.0), _word("", 98.0),
            _word("", 95.0), _word("", 99.0), _word("", 94.0),
            # Solo 2 palabras con texto real, y de baja confianza.
            _word("a", 20.0), _word("b", 15.0),
        )
        result = matching.evaluar_legibilidad(fields)
        # Con solo 2 palabras con texto real, cae por el umbral de cantidad
        # (MIN_WORDS_FOR_CONFIDENCE), no porque el promedio haya quedado
        # inflado por las entradas vacías.
        assert result.legible is False
        assert result.reason == "documento_ilegible"

    def test_ilegible_cuando_confianza_promedio_de_palabras_reales_es_baja(self):
        fields = _fields(
            _word("aaa", 10.0), _word("bbb", 12.0), _word("ccc", 8.0),
            _word("ddd", 15.0), _word("eee", 9.0),
        )
        result = matching.evaluar_legibilidad(fields)
        assert result.legible is False
        assert result.reason == "documento_ilegible"


# ---------------------------------------------------------------------------
# extraer_nombre_probable / agrupación por línea real
# ---------------------------------------------------------------------------
class TestExtraerNombreProbable:
    def test_agrupa_palabras_por_linea_real_no_por_orden_de_deteccion(self):
        """Hallazgo 1 del prototipo: el nombre se pegaba con la última
        palabra del encabezado ("CIUDADANIA JUAN PEREZ GOMEZ") porque el
        texto se unía sin respetar saltos de línea reales. Fix: agrupar por
        (block_num, par_num, line_num) antes de buscar el nombre."""
        fields = _fields(
            _word("CEDULA", 90.0, line=1), _word("DE", 90.0, line=1), _word("CIUDADANIA", 90.0, line=1),
            _word("JUAN", 92.0, line=2), _word("PEREZ", 91.0, line=2), _word("GOMEZ", 89.0, line=2),
        )
        nombre = matching.extraer_nombre_probable(fields)
        assert nombre == "JUAN PEREZ GOMEZ"
        assert "CIUDADANIA" not in nombre

    def test_excluye_encabezados_conocidos_ced_y_rut(self):
        """Hallazgo 3 del prototipo: con un RUT sintético, "REGISTRO UNICO
        TRIBUTARIO" le ganaba en longitud de caracteres al nombre real
        ("EMPRESA DEMO SAS"). Fix: ampliar la lista de exclusión."""
        fields = _fields(
            _word("REGISTRO", 90.0, line=1), _word("UNICO", 90.0, line=1), _word("TRIBUTARIO", 90.0, line=1),
            _word("EMPRESA", 88.0, line=2), _word("DEMO", 87.0, line=2), _word("SAS", 86.0, line=2),
        )
        nombre = matching.extraer_nombre_probable(fields)
        assert nombre == "EMPRESA DEMO SAS"

    def test_excluye_lineas_puramente_numericas(self):
        """Encontrado escribiendo el test del worker (no con OCR real, pero
        misma familia de defecto): un número de documento en su propia
        línea puede ganarle en longitud de caracteres a un nombre corto
        real. Una línea 100% numérica nunca es un nombre."""
        fields = _fields(
            _word("1234567890", 95.0, line=1),
            _word("ANA", 90.0, line=2), _word("DIAZ", 90.0, line=2),
        )
        nombre = matching.extraer_nombre_probable(fields)
        assert nombre == "ANA DIAZ"

    def test_ninguna_linea_candidata_retorna_none(self):
        fields = _fields(_word("REPUBLICA", 90.0, line=1), _word("COLOMBIA", 90.0, line=1))
        assert matching.extraer_nombre_probable(fields) is None


# ---------------------------------------------------------------------------
# corresponde_con_declarado
# ---------------------------------------------------------------------------
class TestCorrespondeConDeclarado:
    def test_corresponde_cuando_nombre_coincide_con_tolerancia_a_ruido(self):
        fields = _fields(_word("JUAN", 90.0, line=1), _word("PEREZ", 90.0, line=1), _word("G0MEZ", 85.0, line=1))
        result = matching.corresponde_con_declarado(fields, nombre_declarado="Juan Perez Gomez")
        assert result.corresponde is True

    def test_no_corresponde_cuando_nombre_no_coincide(self):
        fields = _fields(_word("MARIA", 90.0, line=1), _word("RODRIGUEZ", 90.0, line=1))
        result = matching.corresponde_con_declarado(fields, nombre_declarado="Juan Perez Gomez")
        assert result.corresponde is False

    def test_no_corresponde_cuando_no_hay_nombre_extraible(self):
        fields = _fields(_word("REPUBLICA", 90.0, line=1), _word("COLOMBIA", 90.0, line=1))
        result = matching.corresponde_con_declarado(fields, nombre_declarado="Juan Perez Gomez")
        assert result.corresponde is False
        assert result.nombre_extraido is None


# ---------------------------------------------------------------------------
# evaluar_formato (FE1: formato no admitido / tamaño fuera de rango)
# ---------------------------------------------------------------------------
class TestEvaluarFormato:
    def test_valido_cuando_jpeg_real_declarado_como_jpeg(self):
        data = b"\xff\xd8\xff" + b"\x00" * 2000
        result = matching.evaluar_formato(data, content_type="image/jpeg")
        assert result.valido is True

    def test_valido_cuando_png_real_declarado_como_png(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000
        result = matching.evaluar_formato(data, content_type="image/png")
        assert result.valido is True

    def test_invalido_cuando_los_bytes_no_corresponden_al_content_type_declarado(self):
        # content_type dice JPEG pero los primeros bytes son de un PNG --
        # alguien subió un archivo distinto al que declaró, o lo corrompió.
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000
        result = matching.evaluar_formato(data, content_type="image/jpeg")
        assert result.valido is False
        assert result.reason == "formato_no_admitido"

    def test_invalido_cuando_content_type_no_esta_en_la_lista_admitida(self):
        data = b"\xff\xd8\xff" + b"\x00" * 2000
        result = matching.evaluar_formato(data, content_type="application/zip")
        assert result.valido is False
        assert result.reason == "formato_no_admitido"

    def test_invalido_cuando_el_archivo_es_mas_pequeno_que_el_minimo(self):
        # Un archivo de pocos bytes no es una foto real, es un error de
        # subida (canvas vacío, archivo truncado).
        data = b"\xff\xd8\xff"
        result = matching.evaluar_formato(data, content_type="image/jpeg")
        assert result.valido is False
        assert result.reason == "formato_no_admitido"

    def test_invalido_cuando_el_archivo_excede_el_tamano_maximo(self):
        data = b"\xff\xd8\xff" + b"\x00" * (matching.MAX_FILE_SIZE_BYTES + 1)
        result = matching.evaluar_formato(data, content_type="image/jpeg")
        assert result.valido is False
        assert result.reason == "formato_no_admitido"
