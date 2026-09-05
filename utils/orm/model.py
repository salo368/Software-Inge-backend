"""Base Model con snapshot detached.

Cada operacion abre su propia sesion (por decision de diseno), hace commit y expunge
antes de retornar. Los objetos retornados son detached: los atributos son legibles
pero no disparan flush automatico al modificarlos.

Metodos disponibles en cada subclase:
    Model.get_by_id(id)                     -> snapshot | None
    Model.update_by_id(id, data: dict)      -> snapshot actualizado | None
    Model.delete_by_id(id)                  -> bool
    Model.create(**kwargs)                  -> snapshot nuevo
    Model._get_one(**filters)               -> snapshot | None  (helper interno)
    Model._get_many(**filters)              -> list[snapshot]   (helper interno)
"""
from datetime import datetime
from typing import Self

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from utils.orm.db import get_session


class Base(DeclarativeBase):
    pass


class Model(Base):
    __abstract__ = True

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ---------- Reads ----------

    @classmethod
    def get_by_id(cls, id) -> Self | None:
        with get_session() as s:
            obj = s.get(cls, id)
            if obj is None:
                return None
            s.expunge(obj)
            return obj

    @classmethod
    def _get_one(cls, **filters) -> Self | None:
        with get_session() as s:
            obj = s.query(cls).filter_by(**filters).first()
            if obj is None:
                return None
            s.expunge(obj)
            return obj

    @classmethod
    def _get_many(cls, **filters) -> list[Self]:
        with get_session() as s:
            objs = s.query(cls).filter_by(**filters).all()
            for o in objs:
                s.expunge(o)
            return objs

    # ---------- Writes ----------

    @classmethod
    def create(cls, **kwargs) -> Self:
        with get_session() as s:
            obj = cls(**kwargs)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            s.expunge(obj)
            return obj

    @classmethod
    def update_by_id(cls, id, data: dict) -> Self | None:
        with get_session() as s:
            obj = s.get(cls, id)
            if obj is None:
                return None
            for k, v in data.items():
                setattr(obj, k, v)
            s.commit()
            s.refresh(obj)
            s.expunge(obj)
            return obj

    @classmethod
    def delete_by_id(cls, id) -> bool:
        with get_session() as s:
            obj = s.get(cls, id)
            if obj is None:
                return False
            s.delete(obj)
            s.commit()
            return True

    # ---------- Utilidad ----------

    def to_dict(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
