import json
import os
from datetime import datetime, timezone
from pathlib import Path

from utils.orm.models import TestRuns

BUNDLE = Path(__file__).resolve().parents[2] / "bundle"


class Recorder:
    """Plugin de pytest: persiste cada resultado apenas termina el test."""

    def __init__(self, run_id: int):
        self.run_id = run_id
        self.results: list[dict] = []

    def pytest_runtest_logreport(self, report):
        es_llamada = report.when == "call"
        es_fallo_de_setup = report.when == "setup" and report.outcome != "passed"
        if not es_llamada and not es_fallo_de_setup:
            return
        archivo, _, nombre = report.nodeid.partition("::")
        self.results.append({
            "file": Path(archivo).name,
            "name": nombre,
            "escenario": getattr(report, "description", ""),
            "outcome": report.outcome,
            "duration": round(report.duration, 2),
            "error": str(report.longrepr)[:2000] if report.outcome == "failed" else "",
        })
        TestRuns.update_by_id(self.run_id, {"results": json.dumps(self.results)})


def runner(event, context):
    import pytest

    run_id = event["run_id"]
    os.chdir("/tmp")
    rec = Recorder(run_id)
    try:
        code = pytest.main(
            [str(BUNDLE / "tests"), "-q", "-p", "no:cacheprovider"],
            plugins=[rec],
        )
        status = "passed" if code == 0 else "failed"
    except Exception:
        status = "error"
    TestRuns.update_by_id(run_id, {
        "status": status,
        "results": json.dumps(rec.results),
        "finished_at": datetime.now(timezone.utc),
    })
