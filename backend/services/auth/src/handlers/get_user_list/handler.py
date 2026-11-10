from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.users import Users
from libs.utils.auth import AuthsTypes, require_auth
from libs.utils.params import paginated_response, pagination_params, request_params


@handle_exceptions
@require_auth(AuthsTypes.INTERNAL)
def handler(event, context):

    params = request_params(event)

    search = params.get("search") or ""
    if not isinstance(search, str):
        raise HandledError("invalid_search", 400)
    search = search.strip()

    limit, offset = pagination_params(params)

    total = Users.count_search(search)
    rows = Users.search(search, limit, offset)

    items = [
        {
            "id": row.id,
            "email": row.email,
            "full_name": row.full_name,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]

    return generate_response(paginated_response(items, limit, offset, total), 200)
