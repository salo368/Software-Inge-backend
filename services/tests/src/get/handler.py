import json

from utils.http import err, ok
from utils.orm.models import TestRuns


def get_run(event, context):
    try:
        run_id = int(event["pathParameters"]["id"])
    except (KeyError, ValueError):
        return err(404, "run_not_found")

    r = TestRuns.get_by_id(run_id)
    if r is None:
        return err(404, "run_not_found")

    return ok(200, {
        "id": r.id,
        "status": r.status,
        "started_at": r.created_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "results": json.loads(r.results),
    })
