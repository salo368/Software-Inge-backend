"""Password hashing. Lives apart from auth.py on purpose.

bcrypt ships a compiled native extension, so any service that imports it must
build its wheel for the Lambda (Linux) platform. Only the auth service hashes
or checks passwords, while every service imports require_auth from auth.py --
keeping bcrypt out of that module means the rest only need pure-Python deps.
"""
import bcrypt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False
