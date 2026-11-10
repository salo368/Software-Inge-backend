"""Serves a service's auto-generated API docs.

`utils/build-functions.js` writes `src/_docs/openapi.json` at deploy time and
registers this module as the `api_docs` Lambda of every service with HTTP
routes (not in `pro`):

    GET <prefix>/docs          Swagger UI
    GET <prefix>/openapi.json  the OpenAPI document

Deliberately free of `libs.core` imports: those load the DB config from SSM at
import time, and a docs page has no business needing the database.
"""
from __future__ import annotations

import json
import os

_SPEC_PATH = os.path.join(os.environ.get("LAMBDA_TASK_ROOT", "."), "src", "_docs", "openapi.json")

_SWAGGER_UI = "https://unpkg.com/swagger-ui-dist@5.17.14"

_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="{ui}/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="{ui}/swagger-ui-bundle.js"></script>
  <script>
    // Relative to this page (<prefix>/docs), so it works under any stage URL.
    window.ui = SwaggerUIBundle({{
      url: "./openapi.json",
      dom_id: "#swagger-ui",
      persistAuthorization: true,
      tryItOutEnabled: true,
    }});
  </script>
</body>
</html>
"""


def _response(status: int, body: str, content_type: str) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": content_type}, "body": body}


def _read_spec() -> str:
    with open(_SPEC_PATH, encoding="utf-8") as f:
        return f.read()


def handler(event, context):

    path = (event.get("rawPath") or "").rstrip("/")

    try:
        spec = _read_spec()
    except OSError:
        return _response(404, json.dumps({"error": "docs_not_generated"}), "application/json")

    if path.endswith("/openapi.json"):
        return _response(200, spec, "application/json")

    title = json.loads(spec).get("info", {}).get("title", "API")
    return _response(200, _HTML.format(title=title, ui=_SWAGGER_UI), "text/html; charset=utf-8")
