"""Adaptador local (gratis, sin internet) del puerto `DocumentExtractor`.

Implementación trasladada del prototipo ya validado con OCR real
(`exposicion_C11_recopilar_documentacion.txt` §5 y §7) -- no se reinventa
el algoritmo, solo se traslada al puerto explícito de este servicio.

NOTA DE ENTORNO: requiere el binario `tesseract` instalado en el sistema
(no solo el paquete Python `pytesseract`, que es un wrapper). No está
garantizado en todos los entornos de desarrollo -- por eso ningún test
unitario de este repo llama a `extract()` con una imagen real; los tests
de `domain/matching.py` usan `ExtractedFields` sintéticos, y
`test_ports.py` solo verifica conformidad de interfaz sin invocar OCR. La
extracción real solo se ejercita en `integration.py` (gateado por
`--integration`, igual convención que el resto del backend).
"""
from __future__ import annotations

import pytesseract

from ..ports import ExtractedFields, ExtractedWord


class TesseractAdapter:
    """Adaptador por defecto: `OCR_PROVIDER=local` (o ausente)."""

    def extract(self, image_bytes: bytes) -> ExtractedFields:
        from io import BytesIO

        from PIL import Image

        image = Image.open(BytesIO(image_bytes))
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

        words: list[ExtractedWord] = []
        n = len(data["text"])
        for i in range(n):
            # pytesseract reporta conf=-1 para entradas estructurales sin
            # texto asociado (líneas, párrafos, bloques); se incluyen igual
            # en el modelo de dominio (con su confianza cruda) porque es
            # `domain.matching.evaluar_legibilidad` quien decide filtrarlas
            # por texto vacío -- el adaptador no decide reglas de negocio,
            # solo traduce la forma nativa de Tesseract al modelo único.
            try:
                confidence = float(data["conf"][i])
            except (ValueError, TypeError):
                confidence = -1.0

            words.append(
                ExtractedWord(
                    text=data["text"][i],
                    confidence=confidence,
                    block_num=int(data["block_num"][i]),
                    par_num=int(data["par_num"][i]),
                    line_num=int(data["line_num"][i]),
                )
            )

        return ExtractedFields(words=tuple(words))
