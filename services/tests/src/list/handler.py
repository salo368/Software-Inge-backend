import json

from utils.http import ok
from utils.orm.models import TestRuns


def list_runs(event, context):
    runs = []
    for r in TestRuns.get_recent(20):
        results = json.loads(r.results)
        runs.append({
            "id": r.id,
            "status": r.status,
            "started_at": r.created_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "total": len(results),
            "passed": sum(1 for x in results if x["outcome"] == "passed"),
            "failed": sum(1 for x in results if x["outcome"] == "failed"),
        })
    return ok(200, runs)
