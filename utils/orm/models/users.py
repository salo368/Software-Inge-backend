from typing import Self

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from utils.orm.model import Model


class Users(Model):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    @classmethod
    def get_by_username(cls, username: str) -> Self | None:
        return cls._get_one(username=username)
