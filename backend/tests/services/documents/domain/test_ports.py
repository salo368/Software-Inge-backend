"""Verifica que el adaptador real y el doble de prueba cumplen el mismo
`DocumentExtractor` Protocol -- evita que diverjan en silencio.

No ejecuta Tesseract real (no está garantizado en todos los entornos de
desarrollo). Solo instancia las clases y verifica conformidad estructural
vía `isinstance()`, que `@runtime_checkable` habilita sin tocar OCR. La
excepción es `test_tesseract_adapter_pide_ocr_en_espanol`, que mockea
`pytesseract.image_to_data` para verificar los argumentos de la llamada
sin invocar el binario real.
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

from domain.ports import DocumentExtractor, ExtractedFields  # noqa: E402


def test_tesseract_adapter_cumple_el_protocol_document_extractor():
    from domain.adapters.tesseract_adapter import TesseractAdapter

    adapter = TesseractAdapter()
    assert isinstance(adapter, DocumentExtractor)


def test_tesseract_adapter_pide_ocr_en_espanol():
    """Las cédulas colombianas tienen tildes y eñes; sin lang='spa',
    pytesseract corre con el modelo de inglés por defecto, que las
    degrada. Encontrado al preparar la imagen de contenedor (donde el
    idioma del paquete instalado SÍ importa) -- no se había notado antes
    porque ningún test anterior inspeccionaba los argumentos de la
    llamada real a pytesseract."""
    import io
    from unittest.mock import patch

    from PIL import Image

    from domain.adapters.tesseract_adapter import TesseractAdapter

    img = Image.new("RGB", (10, 10), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    fake_data = {"text": [], "conf": [], "block_num": [], "par_num": [], "line_num": []}
    with patch("pytesseract.image_to_data", return_value=fake_data) as mock_ocr:
        TesseractAdapter().extract(buf.getvalue())

    _, kwargs = mock_ocr.call_args
    assert kwargs.get("lang") == "spa"


def test_fake_extractor_de_pruebas_cumple_el_mismo_protocol():
    class FakeDocumentExtractor:
        def __init__(self, fields: ExtractedFields):
            self._fields = fields

        def extract(self, image_bytes: bytes) -> ExtractedFields:
            return self._fields

    fake = FakeDocumentExtractor(ExtractedFields(words=()))
    assert isinstance(fake, DocumentExtractor)
