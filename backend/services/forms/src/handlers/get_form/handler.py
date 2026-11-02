from libs.core.responses import generate_response, handle_exceptions
from libs.orm.forms import Forms
from libs.utils.auth import require_auth


@handle_exceptions
@require_auth
def handler(event, context):

    user = event.get("user")

    row = Forms.get_by_user_id(user.id)

    form = None
    if row:
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
