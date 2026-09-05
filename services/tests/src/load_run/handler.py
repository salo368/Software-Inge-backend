import json
import os

import boto3

from utils.http import err, ok, parse_body
from utils.orm.models import LoadRuns

RUNNER = os.environ["LOAD_RUNNER_FUNCTION"]
lam = boto3.client("lambda")

# La cuenta tiene limite de 10 ejecuciones Lambda concurrentes: el generador y el
# polling consumen ~2, asi que mas de 8 hilos produce throttling (falsos errores).
SCENARIOS = ("lambda", "db")
MAX_REQUESTS = 400
MAX_CONCURRENCY = 8


def load_run(event, context):
    body = parse_body(event)
    scenario = body.get("scenario")
    if scenario not in SCENARIOS:
        return err(400, "invalid_scenario")
    try:
        total = max(1, min(int(body.get("requests", 100)), MAX_REQUESTS))
        conc = max(1, min(int(body.get("concurrency", 10)), MAX_CONCURRENCY))
    except (TypeError, ValueError):
        return err(400, "invalid_config")

    cfg = {"scenario": scenario, "requests": total, "concurrency": conc}
    row = LoadRuns.create(status="running", config=json.dumps(cfg), results="{}")
    lam.invoke(
        FunctionName=RUNNER,
        InvocationType="Event",
        Payload=json.dumps({"run_id": row.id}).encode(),
    )
    return ok(202, {"id": row.id, "status": "running"})
