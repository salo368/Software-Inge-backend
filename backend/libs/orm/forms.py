from datetime import datetime
from typing import Optional
from uuid import UUID
from enum import Enum

from sqlalchemy import DateTime, String, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

class DocumentType(str, Enum):
    CC = "CC"
    CE = "CE"
    TI = "TI"
    PA = "PA"

class GenderType(str, Enum):
    MALE = "M"
    FEMALE = "F"
    OTHER = "O"

class CivilStatusType(str, Enum):
    SINGLE = "SINGLE"
    MARRIED = "MARRIED"
    DIVORCED = "DIVORCED"
    WIDOWED = "WIDOWED"

class EducationLevelType(str, Enum):
    NONE = "NONE"
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    TECHNICAL = "TECHNICAL"
    TECHNOLOGICAL = "TECHNOLOGICAL"
    PROFESSIONAL = "PROFESSIONAL"
    POSTGRADUATE = "POSTGRADUATE"


class Forms(Base):
    __tablename__ = "forms"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    name: Mapped[Optional[str]] = mapped_column(String(100))
    second_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    second_last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(20))
    birth_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    birth_country: Mapped[Optional[str]] = mapped_column(String(100))
    birth_department: Mapped[Optional[str]] = mapped_column(String(100))
    birth_city: Mapped[Optional[str]] = mapped_column(String(100))
    nationality: Mapped[Optional[str]] = mapped_column(String(100))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    document_type: Mapped[str] = mapped_column(String(20))
    document_number: Mapped[str] = mapped_column(String(30))
    document_issuance_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    document_issuance_country: Mapped[Optional[str]] = mapped_column(String(100))
    document_issuance_department: Mapped[Optional[str]] = mapped_column(String(100))
    document_issuance_city: Mapped[Optional[str]] = mapped_column(String(100))
    phone_ext: Mapped[Optional[str]] = mapped_column(String(10))
    phone_number: Mapped[Optional[str]] = mapped_column(String(20))
    civil_status: Mapped[Optional[str]] = mapped_column(String(20))
    education_level: Mapped[Optional[str]] = mapped_column(String(100))
    is_pep: Mapped[Optional[bool]] = mapped_column(nullable=True)

    monthly_income: Mapped[Optional[float]] = mapped_column(nullable=True)
    monthly_expenses: Mapped[Optional[float]] = mapped_column(nullable=True)
    total_assets: Mapped[Optional[float]] = mapped_column(nullable=True)
    total_liabilities: Mapped[Optional[float]] = mapped_column(nullable=True)
    is_tax_declarant: Mapped[Optional[bool]] = mapped_column(nullable=True)

    @classmethod
    def upsert(cls, user_id: UUID, **fields):
        statement = (
            pg_insert(cls)
            .values(user_id=user_id, **fields)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={**fields, "updated_at": text("NOW()")},
            )
            .returning(cls)
        )
        return db_session.query(statement=statement)

    @classmethod
    def get_by_user_id(cls, user_id: UUID):
        statement = (
            select(cls)
            .where(cls.user_id == user_id)
            .limit(1)
        )
        return db_session.query(statement=statement)