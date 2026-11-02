"""Renders the OTP email body for `request_otp`.

The email is intentionally minimal and country-agnostic:

    * Subject stays short and unbranded ("Your signature verification code")
      so downstream email clients don't wrap it in a promotions folder.
    * Body says the code, the TTL, and repeats the sign_id at the bottom
      so support can look up the ceremony without asking the signer for a
      URL that includes their capability token.
    * No sign URL is included on purpose: the signer already has that URL
      open (they only got to `request_otp` by opening it), and repeating
      it in the email is one more thing an attacker could try to phish.

Callers pass in `signer_name` (optional, may be None) and `expires_at`
(timezone-aware datetime). The plaintext OTP itself is passed in from the
handler AFTER the ORM issues it -- this module never generates codes.
"""

from __future__ import annotations

from datetime import datetime
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
        This code expires at {expires_at_str} (10 minutes after it was issued).
      </p>
      <p style="margin:12px 0 0;color:#555;font-size:13px;">
        If you didn't start this signature, ignore this email &mdash; nothing
        will be signed on your behalf.
      </p>
    </div>
    <div style="padding:14px 28px;background:#fafafa;color:#888;font-size:11px;
                border-top:1px solid #eee;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">
      Ceremony ID: {sign_id_short}
    </div>
  </div>
</div>"""


def render_otp_email(
    *,
    otp: str,
    signer_name: Optional[str],
    expires_at: datetime,
    sign_id: str,
) -> tuple[str, str]:
    """Returns (subject, html_body) for the OTP email.

    `signer_name` is best-effort: the ceremony may have been opened with
    just an email address, in which case we fall back to "there".
    """
    # 6-char prefix is enough for support to disambiguate; the full sign_id
    # is a 32-byte token so leaking a prefix cannot expose the capability.
    sign_id_short = sign_id[:6]
    greeting = (signer_name or "").strip() or "there"
    expires_at_str = expires_at.strftime("%Y-%m-%d %H:%M UTC")
    html = _HTML_TEMPLATE.format(
        greeting=greeting,
        otp=otp,
        expires_at_str=expires_at_str,
        sign_id_short=sign_id_short,
    )
    return _SUBJECT, html
