"""Unit tests for `services/documents/domain/vigencia.py`.

FA1 (Alternativo · Reutilización de vigentes, catálogo C11): un documento
ya validado solo es reutilizable dentro de una ventana de tiempo, no para
siempre. Misma convención de import bare vía sys.path que test_matching.py
y test_ports.py -- módulo block-local sin handler.py colocalizado.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[4]
_DOCUMENTS_SERVICE = _BACKEND / "services" / "documents"
sys.path.insert(0, str(_DOCUMENTS_SERVICE))

for _n in list(sys.modules):
    if _n == "domain" or _n.startswith("domain."):
        sys.modules.pop(_n, None)

from domain import vigencia  # noqa: E402 -- explicit sys.path setup above


def _hace(dias: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=dias)


class TestEsVigente:
    def test_vigente_cuando_la_validacion_es_reciente(self):
        assert vigencia.es_vigente(_hace(1)) is True

    def test_vigente_justo_en_el_limite_de_la_ventana(self):
        assert vigencia.es_vigente(_hace(vigencia.VALIDITY_DAYS)) is True

    def test_no_vigente_cuando_supera_la_ventana(self):
        assert vigencia.es_vigente(_hace(vigencia.VALIDITY_DAYS + 1)) is False

    def test_no_vigente_cuando_la_validacion_es_muy_antigua(self):
        assert vigencia.es_vigente(_hace(1000)) is False
