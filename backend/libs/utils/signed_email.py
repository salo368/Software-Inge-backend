"""Renders the "you signed a document" email for `notify_signed`.

Sent once per signature, right after sign_doc marks it SIGNED. Links to
the full signed PDF (with the evidence page) rather than attaching it:
`mailer.send_email` has no attachment support, and a presigned link
keeps the email small regardless of file size.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

_SUBJECT = "Firmaste un documento"

_HTML_TEMPLATE = """\
<div style="background:#f4f4f7;padding:32px 16px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
  <div style="max-width:520px;margin:auto;background:#fff;border-radius:12px;
              overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08);">
    <div style="padding:24px 28px;border-bottom:1px solid #eee;">
      <div style="font-size:14px;color:#888;letter-spacing:2px;text-transform:uppercase;">
        Firma electronica
      </div>
      <div style="font-size:20px;font-weight:600;color:#111;margin-top:4px;">
        Tu firma quedo registrada
      </div>
    </div>
    <div style="padding:24px 28px;color:#222;font-size:14px;line-height:1.6;">
      <p style="margin:0 0 12px;">Hola {greeting},</p>
      <p style="margin:0 0 20px;">
        Firmaste el documento el {signed_at_str}. Puedes descargar una copia
        firmada (incluye la evidencia de la firma) desde el siguiente enlace:
      </p>
      <p style="margin:0 0 20px;text-align:center;">
        <a href="{signed_url}"
           style="display:inline-block;background:#111;color:#fff;text-decoration:none;
                  padding:12px 24px;border-radius:8px;font-weight:600;">
          Descargar documento firmado
        </a>
      </p>
      <p style="margin:0;color:#555;font-size:13px;">
        Este enlace expira pronto. Si lo necesitas mas adelante, puedes
        volver a generarlo desde la plataforma.
      </p>
    </div>
    <div style="padding:14px 28px;background:#fafafa;color:#888;font-size:11px;
                border-top:1px solid #eee;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">
      ID de la firma: {signature_id_short}
    </div>
  </div>
</div>"""


def render_signed_email(
    *,
    signatory: Optional[str],
    signed_at: datetime,
    signed_url: str,
    signature_id: str,
) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    signature_id_short = str(signature_id)[:8]
    greeting = (signatory or "").strip() or "hola"
    signed_at_str = signed_at.strftime("%Y-%m-%d %H:%M UTC")
    html = _HTML_TEMPLATE.format(
        greeting=greeting,
        signed_at_str=signed_at_str,
        signed_url=signed_url,
        signature_id_short=signature_id_short,
    )
    return _SUBJECT, html
