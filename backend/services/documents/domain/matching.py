"""Dominio de la validación de documentos de C11 (Capturar y validar
documentación de soporte).

Función pura: sin boto3, sin ORM, sin I/O -- mismo molde que
`services/banks/domain/simulacion.py`. Solo conoce el modelo de
`domain.ports.ExtractedFields`, nunca la forma nativa de un proveedor de
OCR concreto (eso es responsabilidad de cada adaptador en `domain/adapters/`).

Las reglas de `evaluar_legibilidad` y `extraer_nombre_probable` no son
arbitrarias: cada umbral y cada exclusión aquí reproduce y corrige un
defecto real encontrado al probar el prototipo con OCR real (no solo con
datos simulados) -- ver `exposicion_C11_recopilar_documentacion.txt` §7.
Probar solo con mocks no los habría encontrado; por eso los tests de este
módulo fijan cada uno como caso explícito, no solo el camino feliz.
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .ports import ExtractedFields, ExtractedWord

# Umbral mínimo de palabras CON TEXTO REAL para considerar la confianza
# promedio estadísticamente significativa. Un documento con 1-2 palabras de
# alta confianza (ej. un sello aislado) no debe pasar como "legible".
MIN_WORDS_FOR_CONFIDENCE = 5

# Confianza promedio mínima (0-100) sobre las palabras con texto real.
MIN_AVG_CONFIDENCE = 40.0

# Score mínimo (rapidfuzz, 0-100) para considerar que el nombre extraído
# corresponde al declarado, tolerando ruido típico de OCR (ej. "G0MEZ" vs
# "GOMEZ").
NAME_MATCH_THRESHOLD = 80.0

# Palabras de encabezado que NUNCA deben considerarse parte de un nombre
# propio. Limitación conocida y documentada (no un descuido): un tipo de
# documento nuevo con un encabezado largo no cubierto aquí puede reproducir
# el mismo error que esta lista corrige. La solución estructural es el modo
# cloud (Azure AI Document Intelligence), que extrae por campo estructurado
# en vez de adivinar por longitud de línea -- ver docs del prototipo.
_HEADER_EXCLUDE = {
    "REPUBLICA", "REPÚBLICA", "COLOMBIA", "CEDULA", "CÉDULA", "CIUDADANIA",
    "CIUDADANÍA", "IDENTIFICACION", "IDENTIFICACIÓN", "REGISTRO", "UNICO",
    "ÚNICO", "TRIBUTARIO", "RUT", "CERTIFICADO", "EXISTENCIA",
    "REPRESENTACION", "REPRESENTACIÓN", "LEGAL", "NIT",
}

# Conectores que no cuentan como "contenido" al decidir si una línea es
# puro encabezado. Sin esto, "CEDULA DE CIUDADANIA" sobrevive como
# candidata (porque "DE" no está en _HEADER_EXCLUDE) y gana por longitud de
# caracteres a un nombre real más corto -- encontrado escribiendo el test
# de agrupación por línea, no con OCR real, pero es la misma familia de
# defecto que los hallazgos del prototipo.
_STOPWORDS = {"DE", "DEL", "LA", "EL", "Y", "A"}


@dataclass(frozen=True)
class LegibilityResult:
    legible: bool
    reason: str | None = None
    avg_confidence: float | None = None


def evaluar_legibilidad(fields: ExtractedFields) -> LegibilityResult:
    """FE1: decide si un documento tiene texto suficiente y confiable.

    Dos condiciones, ambas necesarias (no basta una sola):
      1. Al menos `MIN_WORDS_FOR_CONFIDENCE` palabras con texto real.
      2. Confianza promedio de esas palabras >= `MIN_AVG_CONFIDENCE`.

    La condición 1 existe precisamente porque, sin ella, un documento casi
    en blanco con pocas palabras de alta confianza pasaría como legible; la
    exclusión de palabras SIN texto real (línea de abajo) existe porque,
    sin ella, el ruido estructural que Tesseract reporta sin texto asociado
    infla artificialmente el promedio (hallazgo real del prototipo: una
    imagen de puro ruido daba 95% de confianza promedio).
    """
    words_with_text = [w for w in fields.words if w.text.strip()]
    if len(words_with_text) < MIN_WORDS_FOR_CONFIDENCE:
        return LegibilityResult(legible=False, reason="documento_ilegible")

    avg = sum(w.confidence for w in words_with_text) / len(words_with_text)
    if avg < MIN_AVG_CONFIDENCE:
        return LegibilityResult(legible=False, reason="documento_ilegible", avg_confidence=avg)

    return LegibilityResult(legible=True, avg_confidence=avg)


def _agrupar_por_linea(fields: ExtractedFields) -> list[list[ExtractedWord]]:
    """Agrupa por (block_num, par_num, line_num), preservando el orden de
    aparición de cada línea. NO concatena palabras de líneas distintas --
    es exactamente la corrección del hallazgo 1 del prototipo."""
    groups: dict[tuple[int, int, int], list[ExtractedWord]] = {}
    order: list[tuple[int, int, int]] = []
    for w in fields.words:
        key = (w.block_num, w.par_num, w.line_num)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(w)
    return [groups[k] for k in order]


def extraer_nombre_probable(fields: ExtractedFields) -> str | None:
    """Heurística local (modo Tesseract): la línea de texto más larga que
    no sea, en su totalidad, un encabezado conocido (`_HEADER_EXCLUDE`).

    Limitación conocida, documentada explícitamente (no un descuido): es un
    parche, no una solución estructural. El modo cloud (Azure AI Document
    Intelligence) extrae por campo estructurado y no depende de esta
    heurística.
    """
    candidatas = []
    for linea in _agrupar_por_linea(fields):
        texto = " ".join(w.text for w in linea).strip()
        palabras = texto.upper().split()
        if not palabras:
            continue
        # Una línea puramente numérica es un número de documento o una
        # fecha, nunca un nombre -- sin esto, "1234567890" (10 caracteres)
        # puede ganarle en longitud a un nombre corto real.
        if all(p.isdigit() for p in palabras):
            continue
        contenido = [p for p in palabras if p not in _STOPWORDS]
        if contenido and all(p in _HEADER_EXCLUDE for p in contenido):
            continue
        candidatas.append(texto)

    if not candidatas:
        return None
    return max(candidatas, key=len)


@dataclass(frozen=True)
class CorrespondenceResult:
    corresponde: bool
    nombre_extraido: str | None
    score: float


def corresponde_con_declarado(fields: ExtractedFields, nombre_declarado: str) -> CorrespondenceResult:
    """Contrasta el nombre extraído del documento contra lo que el
    inversionista declaró, con tolerancia a ruido típico de OCR
    (sustituciones de caracteres, orden de palabras) vía *fuzzy matching*.
    """
    nombre_extraido = extraer_nombre_probable(fields)
    if nombre_extraido is None:
        return CorrespondenceResult(corresponde=False, nombre_extraido=None, score=0.0)

    score = fuzz.token_sort_ratio(nombre_extraido.upper(), nombre_declarado.upper())
    return CorrespondenceResult(
        corresponde=score >= NAME_MATCH_THRESHOLD,
        nombre_extraido=nombre_extraido,
        score=score,
    )
