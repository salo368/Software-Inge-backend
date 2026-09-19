import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(value) -> bool:
    return isinstance(value, str) and len(value) <= 320 and bool(_EMAIL_RE.match(value.strip()))


def password_reason(value) -> str | None:
    """Returns error code if invalid; None if OK."""
    if not isinstance(value, str) or not value:
        return "password_required"
    if len(value) < 10:
        return "password_too_short"
    if not any(c.isalpha() for c in value):
        return "password_needs_letter"
    if not any(c.isdigit() for c in value):
        return "password_needs_digit"
    return None
