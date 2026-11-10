"""The OpenAPI generator (`utils/openapi.js`) and its hook in `utils/build-functions.js`.

Runs the real Node code against a throwaway service, so adding an endpoint to
the repo needs no test change. Skipped where Node is not installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

_HANDLERS = {
    "get_thing": """
        @handle_exceptions
        @require_any_auth
        def handler(event, context):
            thing_id = uuid_param(request_params(event), "thing_id", "invalid thing id")
            if thing is None:
                raise HandledError("thing_not_found", 404)
    """,
    "list_things": """
        @handle_exceptions
        @require_auth(AuthsTypes.INTERNAL)
        def handler(event, context):
            params = request_params(event)
            search = params.get("search")
            limit, offset = pagination_params(params)
            if bad:
                raise HandledError("invalid_search", 400)
            raise HandledError(f"invalid_{name}", 400)
    """,
    "make_thing": """
        @handle_exceptions
        @require_auth(AuthsTypes.USER)
        def handler(event, context):
            body = json.loads(event.get("body") or "{}")
            name = body.get("name")
            size = body["size"]
            raise HandledError("name is required")
    """,
    "ping": """
        def handler(event, context):
            return {}
    """,
    "internal_only": """
        def handler(event, context):
            return {}
    """,
}

_FUNCTION_YML = {
    "get_thing": "description: Returns one thing.\nevents:\n  - httpApi: { method: GET, path: /things/get-thing }\n",
    "list_things": "description: Lists things.\nevents:\n  - httpApi: { method: POST, path: /things/list-things }\n",
    "make_thing": "description: Makes a thing.\nevents:\n  - httpApi: { method: POST, path: /things/make-thing }\n",
    "ping": "description: Health.\nevents:\n  - httpApi: GET /things/ping\n",
    "internal_only": "description: Invoke-only, no HTTP.\n",
}


def _make_service(root: Path) -> Path:
    service = root / "things"
    for name, source in _HANDLERS.items():
        folder = service / "src" / "handlers" / name
        folder.mkdir(parents=True)
        (folder / "handler.py").write_text(textwrap.dedent(source), encoding="utf-8")
        (folder / "function.yml").write_text(_FUNCTION_YML[name], encoding="utf-8")
    return service


def _build(service: Path, stage: str) -> dict:
    script = f"""
      const build = require({json.dumps(str(BACKEND / "utils" / "build-functions.js"))})({json.dumps(str(service))});
      build({{ options: {{ stage: {json.dumps(stage)} }}, resolveConfigurationProperty: async () => 'things' }})
        .then((f) => console.log(JSON.stringify(f)));
    """
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, cwd=BACKEND, check=True)
    return json.loads(out.stdout)


@pytest.fixture
def built(tmp_path):
    service = _make_service(tmp_path)
    functions = _build(service, "dev")
    spec = json.loads((service / "src" / "_docs" / "openapi.json").read_text(encoding="utf-8"))
    return service, functions, spec


def test_docs_lambda_is_registered_with_both_routes(built):
    _, functions, _ = built

    docs = functions["api_docs"]
    assert docs["name"] == "cdts-dev-things-api-docs"
    assert docs["handler"] == "libs/utils/openapi_docs.handler"
    assert [e["httpApi"] for e in docs["events"]] == [
        {"method": "GET", "path": "/things/docs"},
        {"method": "GET", "path": "/things/openapi.json"},
    ]


def test_only_http_functions_are_documented(built):
    _, _, spec = built

    assert sorted(spec["paths"]) == [
        "/things/get-thing", "/things/list-things", "/things/make-thing", "/things/ping",
    ]
    assert "api_docs" not in {op["operationId"] for p in spec["paths"].values() for op in p.values()}


def test_auth_is_inferred_from_the_decorators(built):
    _, _, spec = built
    paths = spec["paths"]

    assert paths["/things/get-thing"]["get"]["security"] == [{"userBearer": []}, {"adminBearer": []}]
    assert paths["/things/list-things"]["post"]["security"] == [{"adminBearer": []}]
    assert paths["/things/make-thing"]["post"]["security"] == [{"userBearer": []}]
    assert "security" not in paths["/things/ping"]["get"]


def test_request_fields_are_inferred(built):
    _, _, spec = built
    paths = spec["paths"]

    # read through request_params on a GET -> query string
    assert [(p["name"], p["in"]) for p in paths["/things/get-thing"]["get"]["parameters"]] == [("thing_id", "query")]
    # read through request_params on a POST -> JSON body, with typed pagination
    props = paths["/things/list-things"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert sorted(props) == ["page", "page_size", "search"]
    assert props["page"] == {"type": "integer", "minimum": 1}
    # body.get / body[...]
    props = paths["/things/make-thing"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert sorted(props) == ["name", "size"]


def test_errors_are_inferred_and_dynamic_ones_skipped(built):
    _, _, spec = built
    get_thing = spec["paths"]["/things/get-thing"]["get"]["responses"]
    list_things = spec["paths"]["/things/list-things"]["post"]["responses"]

    assert get_thing["404"]["description"] == "`thing_not_found`"
    assert get_thing["400"]["description"] == "`invalid thing id`, `invalid_json_body`"
    assert sorted(get_thing["401"]["description"].split(", ")) == ["`invalid_or_expired_token`", "`missing_bearer_token`"]
    # pagination_params -> page errors; the f-string error is not guessed
    assert list_things["400"]["description"] == "`invalid_json_body`, `invalid_page`, `invalid_page_size`, `invalid_search`"
    # HandledError(msg) with no status defaults to 400
    assert spec["paths"]["/things/make-thing"]["post"]["responses"]["400"]["description"] == "`name is required`"
    assert "401" not in spec["paths"]["/things/ping"]["get"]["responses"]


def test_pro_gets_no_docs_at_all(tmp_path):
    service = _make_service(tmp_path)

    functions = _build(service, "pro")

    assert "api_docs" not in functions
    assert not (service / "src" / "_docs").exists()


def test_service_without_http_routes_gets_no_docs(tmp_path):
    service = tmp_path / "workers_only"
    folder = service / "src" / "workers" / "on_event"
    folder.mkdir(parents=True)
    (folder / "handler.py").write_text("def handler(event, context):\n    return {}\n", encoding="utf-8")
    (folder / "function.yml").write_text("description: SQS only.\n", encoding="utf-8")

    functions = _build(service, "dev")

    assert "api_docs" not in functions
    assert not (service / "src" / "_docs").exists()


def test_a_malformed_http_event_does_not_break_the_build(tmp_path):
    service = _make_service(tmp_path)
    # A malformed http event is ignored, not fatal to the deploy.
    (service / "src" / "handlers" / "ping" / "function.yml").write_text(
        "description: bad\nevents:\n  - httpApi: 42\n", encoding="utf-8"
    )

    functions = _build(service, "dev")

    assert "ping" in functions
