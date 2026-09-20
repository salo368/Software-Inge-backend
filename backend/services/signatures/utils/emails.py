"""HTML bodies for the two emails the ceremony sends."""
from __future__ import annotations

_SHELL = """\
<div style="background:#f5f3ff;padding:32px 16px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
  <div style="max-width:520px;margin:auto;background:#fff;border-radius:16px;overflow:hidden;
              box-shadow:0 8px 28px rgba(76,29,149,.12);">
    <div style="background:linear-gradient(120deg,#4c1d95,#7c3aed);padding:22px 28px;">
      <div style="color:#fff;font-size:20px;font-weight:700;letter-spacing:-.4px;">CDTs</div>
      <div style="color:rgba(255,255,255,.82);font-size:11px;letter-spacing:1.4px;">{tagline}</div>
    </div>
    <div style="padding:28px;color:#17143a;font-size:14px;line-height:1.6;">{body}</div>
    <div style="padding:16px 28px;background:#faf9fe;color:#6b7280;font-size:11px;">
      Si no reconoces esta solicitud, ignora este correo y no se firmará nada.
    </div>
  </div>
</div>"""


def _money(value) -> str:
    return "$" + f"{float(value):,.0f}".replace(",", ".")


def sign_request_html(*, name: str, bank_name: str, amount, term_days: int,
                      rate, sign_url: str) -> str:
    body = f"""
      <p style="margin:0 0 14px;">Hola <b>{name}</b>,</p>
      <p style="margin:0 0 18px;">Tu orden de inversión está lista para firmar. El proceso toma menos
      de 3 minutos: revisas el documento, validas tu identidad y confirmas con un código.</p>
      <table style="width:100%;border-collapse:collapse;background:#faf9fe;border-radius:10px;">
        <tr><td style="padding:10px 14px;color:#6b7280;font-size:12px;">Entidad</td>
            <td style="padding:10px 14px;text-align:right;font-weight:700;">{bank_name}</td></tr>
        <tr><td style="padding:10px 14px;color:#6b7280;font-size:12px;">Monto</td>
            <td style="padding:10px 14px;text-align:right;font-weight:700;">{_money(amount)}</td></tr>
        <tr><td style="padding:10px 14px;color:#6b7280;font-size:12px;">Plazo y tasa</td>
            <td style="padding:10px 14px;text-align:right;font-weight:700;">{term_days} días · {float(rate):.2f}% E.A.</td></tr>
      </table>
      <p style="text-align:center;margin:26px 0 8px;">
        <a href="{sign_url}" style="background:#7c3aed;color:#fff;padding:13px 30px;border-radius:10px;
           text-decoration:none;font-weight:700;display:inline-block;">Firmar mi orden</a>
      </p>
      <p style="color:#6b7280;font-size:11px;text-align:center;margin:0;word-break:break-all;">{sign_url}</p>
    """
    return _SHELL.format(tagline="FIRMA DIGITAL", body=body)


def otp_html(otp: str) -> str:
    body = f"""
      <p style="margin:0 0 10px;">Tu código para confirmar la firma es:</p>
      <div style="text-align:center;margin:22px 0;">
        <span style="display:inline-block;background:#f5f3ff;border:1px dashed #c4b5fd;border-radius:12px;
                     padding:14px 26px;font-size:32px;letter-spacing:10px;font-weight:700;color:#4c1d95;">{otp}</span>
      </div>
      <p style="color:#6b7280;font-size:12px;margin:0;">Vence en 10 minutos y solo se puede usar una vez.</p>
    """
    return _SHELL.format(tagline="CÓDIGO DE FIRMA", body=body)
