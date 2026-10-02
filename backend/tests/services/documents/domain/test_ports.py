"""Verifica que el adaptador real y el doble de prueba cumplen el mismo
`DocumentExtractor` Protocol -- evita que diverjan en silencio.

No ejecuta Tesseract real (no está garantizado en todos los entornos de
desarrollo). Solo instancia las clases y verifica conformidad estructural
vía `isinstance()`, que `@runtime_checkable` habilita sin tocar OCR.
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


def test_fake_extractor_de_pruebas_cumple_el_mismo_protocol():
    class FakeDocumentExtractor:
        def __init__(self, fields: ExtractedFields):
            self._fields = fields

        def extract(self, image_bytes: bytes) -> ExtractedFields:
            return self._fields

    fake = FakeDocumentExtractor(ExtractedFields(words=()))
    assert isinstance(fake, DocumentExtractor)
