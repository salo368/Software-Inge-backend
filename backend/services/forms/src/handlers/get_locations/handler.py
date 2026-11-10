from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.utils.locations import ColombianLocations, Countries


class LocationType:
    COLOMBIAN_LOCATIONS = "colombian_locations"
    COUNTRIES = "countries"


def handle_colombian_locations() -> dict:
    data = ColombianLocations._load_data()
    result = {}
    for dep_key, dep_info in data.items():
        cities = {}
        for city_key, city_info in dep_info.get("cities", {}).items():
            city = {"label": city_info.get("label", city_key)}
            if city_info.get("localities"):
                city["localities"] = {
                    loc_key: {"label": loc_info.get("label", loc_key)}
                    for loc_key, loc_info in city_info["localities"].items()
                }
            cities[city_key] = city
        result[dep_key] = {
            "label": dep_info.get("label", dep_key),
            "cities": cities,
        }
    return result


def handle_countries() -> dict:
    return Countries.get_countries_map()


@handle_exceptions
def handler(event, context):

    query_params = event.get("queryStringParameters") or {}
    location_type = query_params.get("type")

    if location_type == LocationType.COLOMBIAN_LOCATIONS:
        data = handle_colombian_locations()
    elif location_type == LocationType.COUNTRIES:
        data = handle_countries()
    else:
        raise HandledError(
            "Invalid or missing 'type' query parameter. "
            "Expected 'colombian_locations' or 'countries'.",
            400,
        )

    return generate_response(
        {"data": data},
        200,
        headers={"Cache-Control": "public, max-age=7200"},
    )
