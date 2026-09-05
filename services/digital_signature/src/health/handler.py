import json
import os


def health(event, context):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "status": "ok",
            "service": os.environ.get("SERVICE"),
            "stage": os.environ.get("STAGE"),
        }),
    }
