"""Helpers minimos para respuestas HTTP en handlers Lambda."""
import json


def ok(status: int = 200, body: dict | list | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body if body is not None else {}, default=str),
    }


def err(status: int, code: str, detail: str | None = None) -> dict:
    body = {"error": code}
    if detail:
        body["detail"] = detail
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def parse_body(event: dict) -> dict | None:
    """Parsea event['body'] como JSON. Retorna dict o None si es invalido."""
    try:
        return json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return None
