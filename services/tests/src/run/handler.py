import json
import os

import boto3

from utils.http import ok
from utils.orm.models import TestRuns

RUNNER = os.environ["RUNNER_FUNCTION"]
lam = boto3.client("lambda")


def run(event, context):
    row = TestRuns.create(status="running", results="[]")
    lam.invoke(
        FunctionName=RUNNER,
        InvocationType="Event",
        Payload=json.dumps({"run_id": row.id}).encode(),
    )
    return ok(202, {"id": row.id, "status": "running"})
