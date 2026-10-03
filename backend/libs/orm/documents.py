from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base
from libs.orm.processes import Processes

# C11 -- "Capturar y validar documentación de soporte". Flujo básico (FB):
# pendiente -> validando -> validado | rechazado. FA1 (reutilización de
# vigentes) y FE1 (formato no admitido) ya están cubiertos -- ver
# get_vigente/register_reused más abajo y domain/matching.evaluar_formato.
# FE2 (vencido) y FA2 (documentación corporativa) siguen siendo slices
# futuros -- no se modela su estado todavía a propósito.
STAGES = ("pendiente", "validando", "validado", "rechazado")

# Motivos de rechazo estables (el frontend los usa para distinguir cada
# caso sin parsear texto libre).
REJECTION_REASONS = ("documento_ilegible", "no_corresponde", "formato_no_admitido")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Documentos(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    process_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("processes.id", ondelete="CASCADE")
    )
    document_type: Mapped[str] = mapped_column(String(50))
    stage: Mapped[str] = mapped_column(String(20), default="pendiente")
    s3_key_raw: Mapped[str] = mapped_column(Text, unique=True)
    s3_key_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hash_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "document_type": self.document_type,
            "stage": self.stage,
            "rejection_reason": self.rejection_reason,
            "hash_sha256": self.hash_sha256,
            "uploaded_at": self.uploaded_at.isoformat(),
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
        }

    @classmethod
    def get_by_s3_key(cls, s3_key_raw: str):
        stmt = select(cls).where(cls.s3_key_raw == s3_key_raw).limit(1)
        return db_session.session.execute(stmt).scalars().first()

    @classmethod
    def get_by_id(cls, document_id: UUID):
        return db_session.session.get(cls, document_id)

    @classmethod
    def list_by_process(cls, process_id: UUID):
        stmt = (
            select(cls)
            .where(cls.process_id == process_id)
            .order_by(cls.uploaded_at.desc())
        )
        return list(db_session.session.execute(stmt).scalars().all())

    @classmethod
    def register_from_s3(cls, *, process_id: UUID, document_type: str, s3_key_raw: str):
        row = cls(
            process_id=process_id,
            document_type=document_type,
            stage="validando",
            s3_key_raw=s3_key_raw,
        )
        db_session.session.add(row)
        db_session.session.flush()
        return row

    def mark_validado(self, *, s3_key_evidence: str, hash_sha256: str) -> None:
        self.stage = "validado"
        self.s3_key_evidence = s3_key_evidence
        self.hash_sha256 = hash_sha256
        self.validated_at = _utcnow()

    def mark_rechazado(self, *, reason: str) -> None:
        assert reason in REJECTION_REASONS, f"unknown rejection reason: {reason}"
        self.stage = "rechazado"
        self.rejection_reason = reason

    @classmethod
    def get_vigente(cls, *, user_id: UUID, document_type: str):
        """FA1: el documento validado más reciente de CUALQUIER proceso
        del usuario, para ese tipo de documento (soporta el escenario de
        inversionista recurrente, E02). No aplica la ventana de vigencia
        aquí -- es una regla de negocio (domain.vigencia.es_vigente), y
        quien llama decide si el resultado todavía sirve."""
        stmt = (
            select(cls)
            .join(Processes, Processes.id == cls.process_id)
            .where(
                Processes.user_id == user_id,
                cls.document_type == document_type,
                cls.stage == "validado",
            )
            .order_by(cls.validated_at.desc())
            .limit(1)
        )
        return db_session.session.execute(stmt).scalars().first()

    @classmethod
    def register_reused(cls, *, process_id: UUID, document_type: str, source: "Documentos"):
        """FA1: crea una fila ya validada para `process_id`, apuntando a
        la MISMA evidencia en S3 que `source` -- no se copia el archivo,
        porque la evidencia validada es inmutable una vez escrita (mismo
        criterio de retención que protege evidencia-validada/). s3_key_raw
        es sintético (nunca existió una subida real) pero único, para
        respetar la restricción de la columna."""
        row = cls(
            process_id=process_id,
            document_type=document_type,
            stage="validado",
            s3_key_raw=f"reused/{process_id}/{document_type}/{uuid4()}",
            s3_key_evidence=source.s3_key_evidence,
            hash_sha256=source.hash_sha256,
            validated_at=_utcnow(),
        )
        db_session.session.add(row)
        db_session.session.flush()
        return row


class DocumentEvents(Base):
    """Bitácora de auditoría append-only (Q22R01). Nunca se actualiza una
    fila existente -- cada evento es un hecho nuevo, no una edición."""

    __tablename__ = "document_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(50))
    actor: Mapped[str] = mapped_column(String(100))
    result: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    @classmethod
    def record(cls, *, document_id: UUID, event_type: str, actor: str, result: Optional[str] = None):
        row = cls(document_id=document_id, event_type=event_type, actor=actor, result=result)
        db_session.session.add(row)
        db_session.session.flush()
        return row
