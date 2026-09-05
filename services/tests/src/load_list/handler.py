import json

from utils.http import ok
from utils.orm.models import LoadRuns


def load_list(event, context):
    runs = []
    for r in LoadRuns.get_recent(20):
        cfg = json.loads(r.config)
        res = json.loads(r.results)
        runs.append({
            "id": r.id,
            "status": r.status,
            "started_at": r.created_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "scenario": cfg.get("scenario"),
            "requests": cfg.get("requests", 0),
            "concurrency": cfg.get("concurrency", 0),
            "done": res.get("done", 0),
            "ok": res.get("ok", 0),
            "p95": res.get("p95"),
        })
    return ok(200, runs)
