import boto3

from utils.auth.middleware import require_auth
from utils.http import err, ok
from utils.orm.models import Cdts

s3 = boto3.client("s3")


@require_auth
def contract(event, context):
    try:
        cdt_id = int(event["pathParameters"]["id"])
    except (KeyError, ValueError):
        return err(404, "cdt_not_found")

    cdt = Cdts.get_by_id(cdt_id)
    if cdt is None or cdt.user_id != event["auth"].user.id:
        return err(404, "cdt_not_found")
    if not cdt.signature_url or not cdt.signature_url.startswith("s3://"):
        return err(404, "contract_not_signed")

    bucket, _, key = cdt.signature_url[5:].partition("/")
    view_url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=900
    )
    download_url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="cdt-{cdt.id}-contrato-firmado.pdf"',
        },
        ExpiresIn=900,
    )
    return ok(200, {"view_url": view_url, "download_url": download_url})
