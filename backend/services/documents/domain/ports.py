"""Puerto del caso de uso C11 (Capturar y validar documentación de soporte).

`DocumentExtractor` es el único punto de contacto entre el dominio y
cualquier proveedor de OCR/Document Intelligence. `domain/matching.py`
nunca importa `pytesseract` ni ningún SDK de nube -- solo conoce esta forma
(Anti-Corruption Layer). Esto es lo que en el análisis de arquitectura de
`signatures` (docs/add-signatures-uc3.md) se señaló como una deuda: ahí el
puerto hacia el proveedor de firma (`mock_ca.py`) es implícito. Aquí se
declara explícito desde el primer commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ExtractedWord:
    """Una palabra detectada, ya normalizada al modelo de dominio.

    `block_num`/`par_num`/`line_num` preservan la agrupación por línea real
    del documento -- necesarios para `extraer_nombre_probable` en
    `matching.py`; sin ellos, palabras de líneas distintas se concatenan en
    el orden de detección, no en el orden visual (bug real encontrado con
    OCR real, ver `exposicion_C11_recopilar_documentacion.txt` §7).
    """

    text: str
    confidence: float  # 0-100
    block_num: int
    par_num: int
    line_num: int


@dataclass(frozen=True)
class ExtractedFields:
    """Resultado de extracción ya traducido al modelo de dominio único.

    Tesseract reporta confianza y posición por palabra; Azure AI Document
    Intelligence reporta campos estructurados. Cada adaptador en
    `domain/adapters/` es responsable de traducir la forma nativa de su
    proveedor a esta estructura -- el dominio nunca ve ninguna de las dos
    formas nativas.
    """

    words: tuple[ExtractedWord, ...]


@runtime_checkable
class DocumentExtractor(Protocol):
    """Puerto que cualquier proveedor de extracción debe implementar.

    `@runtime_checkable` permite verificar con `isinstance()` que tanto el
    adaptador real (`TesseractAdapter`) como el doble de prueba usado en los
    tests de handlers (`FakeDocumentExtractor`) cumplen la misma forma --
    sin eso, el puerto podría divergir en silencio entre la implementación
    real y la de pruebas.
    """

    def extract(self, image_bytes: bytes) -> ExtractedFields:
        ...
