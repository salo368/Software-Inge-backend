"""Renders the OTP email body for `set_otp`. Ported from
services/signatures/_legacy/utils/otp_email.py, adapted to this
service's simplified schema (signature_id instead of sign_id, no
separate signer_name/signer_email columns beyond `signatory`/`email`).

The email intentionally says only the code and its TTL -- no sign URL,
since the signer already has that URL open (that's how they got here).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


_SUBJECT = "Your signature verification code"

_HTML_TEMPLATE = """\
<div style="background:#f4f4f7;padding:32px 16px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
  <div style="max-width:520px;margin:auto;background:#fff;border-radius:12px;
              overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08);">
    <div style="padding:24px 28px;border-bottom:1px solid #eee;">
      <div style="font-size:14px;color:#888;letter-spacing:2px;text-transform:uppercase;">
        Signature verification
      </div>
      <div style="font-size:20px;font-weight:600;color:#111;margin-top:4px;">
        Confirm you want to sign
      </div>
    </div>
    <div style="padding:24px 28px;color:#222;font-size:14px;line-height:1.6;">
      <p style="margin:0 0 12px;">Hi {greeting},</p>
      <p style="margin:0 0 20px;">Use the code below to confirm the signature you
      started. Do not share this code with anyone.</p>
      <div style="background:#f4f4f7;border-radius:10px;padding:20px 24px;
                  text-align:center;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
                  font-size:32px;letter-spacing:8px;color:#111;">
        {otp}
      </div>
      <p style="margin:20px 0 0;color:#555;font-size:13px;">
        This code expires at {expires_at_str} ({ttl_minutes} minutes after it was issued).
      </p>
      <p style="margin:12px 0 0;color:#555;font-size:13px;">
        If you didn't start this signature, ignore this email &mdash; nothing
        will be signed on your behalf.
      </p>
    </div>
    <div style="padding:14px 28px;background:#fafafa;color:#888;font-size:11px;
                border-top:1px solid #eee;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">
      Signature ID: {signature_id_short}
    </div>
  </div>
</div>"""


def render_otp_email(
    *,
    otp: str,
    signatory: Optional[str],
    issued_at: datetime,
    ttl: timedelta,
    signature_id: str,
) -> tuple[str, str]:
    """Returns (subject, html_body) for the OTP email."""
    signature_id_short = str(signature_id)[:8]
    greeting = (signatory or "").strip() or "there"
    expires_at_str = (issued_at + ttl).strftime("%Y-%m-%d %H:%M UTC")
    html = _HTML_TEMPLATE.format(
        greeting=greeting,
        otp=otp,
        expires_at_str=expires_at_str,
        ttl_minutes=int(ttl.total_seconds() // 60),
        signature_id_short=signature_id_short,
    )
    return _SUBJECT, html
