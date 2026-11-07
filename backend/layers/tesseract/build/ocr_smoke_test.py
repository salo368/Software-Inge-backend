"""Smoke test for the real Tesseract Lambda Layer binary + language data.

Run this INSIDE a container based on the exact Lambda base image used in
production (public.ecr.aws/lambda/python:3.12), with the Layer content
mounted at /opt -- see local-ocr-test.sh in this same directory, which sets
that up. That image already puts /opt/bin on PATH and /opt/lib on
LD_LIBRARY_PATH by default (AWS wires this for every Lambda regardless of
whether it references a Layer), so mounting the Layer there and importing
the real services/documents/domain/adapters/tesseract_adapter.py is the
closest local proxy to "the real deployed documents/on_upload Lambda can
read a document" without needing AWS credentials or an actual deploy.

This is NOT a pytest test and is NOT collected by the backend suite: it
needs the real `tesseract` ELF binary, which only runs on Linux, so it
cannot execute on a plain Windows/macOS dev machine outside Docker.
"""
from __future__ import annotations

import io
import sys

sys.path.insert(0, "/var/task")  # services/documents, mounted read-only by the wrapper script

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from domain.adapters.tesseract_adapter import TesseractAdapter  # noqa: E402

NOMBRE = "JUAN PEREZ"
NUMERO = "1000234567"


def _synthetic_id_image() -> bytes:
    """Renders NOMBRE/NUMERO onto a blank canvas as a stand-in for a real
    scanned document. Good enough to prove the OCR pipeline end-to-end
    (binary + shared libs + spa language data + the adapter's parsing of
    pytesseract's output) without needing a real ID photo on hand."""
    img = Image.new("RGB", (1200, 400), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=60)
    draw.text((40, 80), NOMBRE, fill="black", font=font)
    draw.text((40, 220), NUMERO, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def main() -> None:
    image_bytes = _synthetic_id_image()

    fields = TesseractAdapter().extract(image_bytes)
    recognized = " ".join(w.text for w in fields.words if w.text.strip())

    print(f"OCR crudo reconocido: {recognized!r}")

    assert "JUAN" in recognized.upper(), (
        "El binario tesseract del Layer no reconocio el nombre esperado -- "
        f"texto crudo: {recognized!r}"
    )
    assert NUMERO in recognized, (
        "El binario tesseract del Layer no reconocio el numero esperado -- "
        f"texto crudo: {recognized!r}"
    )
    print("OK: tesseract + leptonica + libs + lang=spa del Layer funcionan end-to-end.")


if __name__ == "__main__":
    main()
