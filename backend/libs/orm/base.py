from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):

    def to_dict(self) -> dict:
        out = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        for k, v in out.items():
            if isinstance(v, (datetime, UUID)):
                out[k] = str(v) if isinstance(v, UUID) else v.isoformat()
        return out
