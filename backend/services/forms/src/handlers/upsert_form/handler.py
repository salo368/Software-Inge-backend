import json
import re
from datetime import date, datetime, timezone

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.forms import CivilStatusType, DocumentType, EducationLevelType, Forms, GenderType
from libs.utils.auth import require_auth
from libs.utils.locations import Countries, IssuanceLocation, Location

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _string(body, key, required=True, uppercase=False):
    value = body.get(key)
    if value is None:
        if required:
            raise HandledError(f"{key} is required", 400)
        return None
    if not isinstance(value, str) or not value.strip():
        raise HandledError(f"{key} must be a non-empty string", 400)
    value = value.strip()
    return value.upper() if uppercase else value


def _enum(body, key, enum_cls, required=True):
    value = body.get(key)
    if value is None:
        if required:
            raise HandledError(f"{key} is required", 400)
        return None
    valid = {member.value for member in enum_cls}
    if value not in valid:
        raise HandledError(f"{key} must be one of {sorted(valid)}", 400)
    return value


def _date(body, key, required=True):
    raw = body.get(key)
    if raw is None:
        if required:
            raise HandledError(f"{key} is required", 400)
        return None
    try:
        parsed = date.fromisoformat(str(raw))
    except ValueError:
        raise HandledError(f"{key} must be a valid date (YYYY-MM-DD)", 400)
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)


def _bool(body, key, required=True):
    value = body.get(key)
    if value is None:
        if required:
            raise HandledError(f"{key} is required", 400)
        return None
    if not isinstance(value, bool):
        raise HandledError(f"{key} must be true or false", 400)
    return value


def _float(body, key, required=True):
    value = body.get(key)
    if value is None:
        if required:
            raise HandledError(f"{key} is required", 400)
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise HandledError(f"{key} must be a number", 400)
    if parsed < 0:
        raise HandledError(f"{key} must be >= 0", 400)
    return parsed


def _country(body, key, required=True):
    value = _string(body, key, required=required)
    if value is not None and not Countries.get_country(value):
        raise HandledError(f"{key} is not a valid country", 400)
    return value


def _location(body, prefix, location_cls, required=True):
    country = _country(body, f"{prefix}_country", required=required)
    department = _string(body, f"{prefix}_department", required=required)
    city = _string(body, f"{prefix}_city", required=required)

    if country == Location.COLOMBIA_KEY and (department or city):
        if location_cls(country, department, city).city_label is None:
            raise HandledError(f"{prefix}_department/{prefix}_city is not valid", 400)

    return country, department, city


@handle_exceptions
@require_auth
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    user = event["user"]

    name = _string(body, "name", uppercase=True)
    second_name = _string(body, "second_name", required=False, uppercase=True)
    last_name = _string(body, "last_name", uppercase=True)
    second_last_name = _string(body, "second_last_name", required=False, uppercase=True)

    document_number = body.get("document_number")
    if document_number is None:
        raise HandledError("document_number is required", 400)
    document_number = str(document_number).strip()
    if not document_number.isdigit():
        raise HandledError("document_number must be numeric", 400)

    document_type = body.get("document_type")
    if document_type is None:
        raise HandledError("document_type is required", 400)
    if document_type not in {member.value for member in DocumentType}:
        raise HandledError(
            f"document_type must be one of {sorted(m.value for m in DocumentType)}", 400
        )

    email = body.get("email")
    if email is None:
        raise HandledError("email is required", 400)
    if not isinstance(email, str) or not _EMAIL_RE.match(email.strip()):
        raise HandledError("email is not valid", 400)
    email = email.strip().lower()

    gender = _enum(body, "gender", GenderType)
    birth_date = _date(body, "birth_date")
    birth_country, birth_department, birth_city = _location(body, "birth", Location)
    nationality = _country(body, "nationality")
    document_issuance_date = _date(body, "document_issuance_date")
    document_issuance_country, document_issuance_department, document_issuance_city = (
        _location(body, "document_issuance", IssuanceLocation)
    )
    phone_ext = _string(body, "phone_ext")
    phone_number = _string(body, "phone_number")
    civil_status = _enum(body, "civil_status", CivilStatusType)
    education_level = _enum(body, "education_level", EducationLevelType)
    is_pep = _bool(body, "is_pep")
    monthly_income = _float(body, "monthly_income")
    monthly_expenses = _float(body, "monthly_expenses")
    total_assets = _float(body, "total_assets")
    total_liabilities = _float(body, "total_liabilities")
    is_tax_declarant = _bool(body, "is_tax_declarant")

    row = Forms.upsert(
        user.id,
        name=name,
        second_name=second_name,
        last_name=last_name,
        second_last_name=second_last_name,
        gender=gender,
        birth_date=birth_date,
        birth_country=birth_country,
        birth_department=birth_department,
        birth_city=birth_city,
        nationality=nationality,
        email=email,
        document_type=document_type,
        document_number=document_number,
        document_issuance_date=document_issuance_date,
        document_issuance_country=document_issuance_country,
        document_issuance_department=document_issuance_department,
        document_issuance_city=document_issuance_city,
        phone_ext=phone_ext,
        phone_number=phone_number,
        civil_status=civil_status,
        education_level=education_level,
        is_pep=is_pep,
        monthly_income=monthly_income,
        monthly_expenses=monthly_expenses,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        is_tax_declarant=is_tax_declarant,
    )

    form = {
        "name": row.name,
        "second_name": row.second_name,
        "last_name": row.last_name,
        "second_last_name": row.second_last_name,
        "gender": row.gender,
        "birth_date": row.birth_date.strftime("%d/%m/%Y"),
        "birth_country": row.birth_country,
        "birth_department": row.birth_department,
        "birth_city": row.birth_city,
        "nationality": row.nationality,
        "email": row.email,
        "document_type": row.document_type,
        "document_number": row.document_number,
        "document_issuance_date": row.document_issuance_date.strftime("%d/%m/%Y"),
        "document_issuance_country": row.document_issuance_country,
        "document_issuance_department": row.document_issuance_department,
        "document_issuance_city": row.document_issuance_city,
        "phone_ext": row.phone_ext,
        "phone_number": row.phone_number,
        "civil_status": row.civil_status,
        "education_level": row.education_level,
        "is_pep": row.is_pep,
        "monthly_income": row.monthly_income,
        "monthly_expenses": row.monthly_expenses,
        "total_assets": row.total_assets,
        "total_liabilities": row.total_liabilities,
        "is_tax_declarant": row.is_tax_declarant,
        "updated_at": row.updated_at,
    }

    return generate_response({"form": form})
