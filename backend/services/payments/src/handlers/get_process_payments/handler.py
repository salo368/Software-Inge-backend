import os
from decimal import Decimal

from libs.core.responses import generate_response, handle_exceptions
from libs.core.s3 import presign_download
from libs.orm.payments import Payments
from libs.utils.auth import AuthsTypes, require_auth
from libs.utils.params import request_params, uuid_param

BUCKET = os.environ["FILES_BUCKET"]


@handle_exceptions
@require_auth(AuthsTypes.INTERNAL)
def handler(event, context):

    process_id = uuid_param(request_params(event), "process_id", "invalid process id")

    rows = Payments.list_by_process(process_id)

    # Summed in Decimal, like create_payment does, before going out as float.
    total = sum((row.amount for row in rows), Decimal("0"))

    payments = [
        {
            "id": row.id,
            "amount": float(row.amount),
            "s3_file": row.s3_file,
            "receipt_url": presign_download(BUCKET, row.s3_file) if row.s3_file else None,
        }
        for row in rows
    ]

    return generate_response({"payments": payments, "total_paid": float(total)}, 200)
