import json
from uuid import UUID

from libs.core.responses import HandledError


def request_params(event) -> dict:
    """Query string merged with the JSON body (body wins). Lets one handler
    be called as `GET ?process_id=...` or with a body, whichever the client
    can send."""

    params = dict(event.get("queryStringParameters") or {})

    raw = event.get("body")
    if raw:
        try:
            body = json.loads(raw)
        except ValueError:
            raise HandledError("invalid_json_body", 400)
        if isinstance(body, dict):
            params.update(body)

    return params


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _positive_int(params: dict, name: str, default: int, maximum: int | None = None) -> int:

    raw = params.get(name)
    if raw is None or raw == "":
        return default

    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HandledError(f"invalid_{name}", 400)

    if value < 1 or (maximum is not None and value > maximum):
        raise HandledError(f"invalid_{name}", 400)

    return value


def pagination_params(params: dict) -> tuple[int, int]:
    """(limit, offset) from `page` (>= 1, default 1) and `page_size`
    (1..MAX_PAGE_SIZE, default DEFAULT_PAGE_SIZE)."""

    page = _positive_int(params, "page", 1)
    page_size = _positive_int(params, "page_size", DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)

    return page_size, (page - 1) * page_size


def paginated_response(items: list, limit: int, offset: int, total: int) -> dict:

    return {
        "results": items,
        "count": len(items),
        "pagination": {"offset": offset, "limit": limit, "total": total},
    }


def uuid_param(params: dict, name: str, error: str) -> UUID:

    try:
        return UUID(str(params.get(name)))
    except (TypeError, ValueError):
        raise HandledError(error, 400)
