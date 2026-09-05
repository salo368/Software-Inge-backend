from typing import Self

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from utils.orm.model import Model


class Files(Model):
    __tablename__ = "files"

    cdt_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cdts.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    s3_url: Mapped[str] = mapped_column(Text, nullable=False)

    @classmethod
    def get_by_cdt_id(cls, cdt_id: int) -> list[Self]:
        return cls._get_many(cdt_id=cdt_id)
