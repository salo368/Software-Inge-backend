"""FA1 (Alternativo · Reutilización de vigentes, catálogo C11).

Función pura: no sabe nada de la ORM ni de `Documentos`, solo recibe una
fecha de validación y decide si cae dentro de la ventana de reutilización.
Separado de `matching.py` a propósito -- es una regla temporal, no una
regla sobre el contenido del documento, y vive en su propio módulo por la
misma razón que `signatures/utils` reparte sus responsabilidades en
archivos pequeños de un solo concern (stamp.py, evidence.py, emails.py).

La ventana de 365 días es una decisión de negocio, no técnica: una cédula
colombiana no vence, pero el expediente KYC del que forma parte sí debe
refrescarse periódicamente (mismo criterio que la re-verificación
periódica de C04). Si el negocio define un valor distinto, cambia aquí y
en ningún otro lugar -- `Documentos.get_vigente` no duplica el umbral.
"""
from __future__ import annotations

from datetime import datetime, timezone

VALIDITY_DAYS = 365


def es_vigente(validated_at: datetime, *, ahora: datetime | None = None) -> bool:
    ahora = ahora or datetime.now(timezone.utc)
    return (ahora - validated_at).days <= VALIDITY_DAYS
