"""Authenticated document ownership around the existing ingestion engine."""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pydebugger.models import DocumentSource, ExecutionJob, IngestionJob, JobState

from ..database import Database
from ..models import DocumentRecord, ExecutionJobRecord, IngestionJobRecord
from ..schemas.documents import source_from_record
from .job_persistence import (
    apply_execution_job,
    apply_ingestion_job,
    ingestion_job_from_record,
)


class EngineSettings(Protocol):
    upload_limit_bytes: int


class DocumentEngine(Protocol):
    settings: EngineSettings

    def start_document_ingestion(
        self,
        filename: str,
        data: bytes,
        media_type: str | None,
        owner_id: str | None = None,
    ) -> IngestionJob: ...

    def start_youtube_ingestion(
        self,
        reference: str,
        languages: tuple[str, ...],
        owner_id: str | None = None,
    ) -> IngestionJob: ...

    def get_ingestion(self, job_id: str) -> IngestionJob: ...

    def cancel_ingestion(self, job_id: str) -> bool: ...

    def list_documents(self) -> tuple[DocumentSource, ...]: ...

    def remove_document(self, document_id: str) -> bool: ...


class OwnedResourceNotFoundError(LookupError):
    """Raised without revealing whether another user owns the resource."""


class DocumentService:
    def __init__(
        self, engine: DocumentEngine, database: Database | None = None
    ) -> None:
        self.engine = engine
        self._database: Database | None = None
        if database is not None:
            self.bind_database(database)

    def bind_database(self, database: Database) -> None:
        self._database = database
        ingestion = getattr(self.engine, "ingestion_jobs", None)
        execution = getattr(self.engine, "execution", None)
        if ingestion is not None and hasattr(ingestion, "set_listener"):
            ingestion.set_listener(self._persist_ingestion_update)
        if execution is not None and hasattr(execution, "set_listener"):
            execution.set_listener(self._persist_execution_update)

    @property
    def upload_limit_bytes(self) -> int:
        return int(self.engine.settings.upload_limit_bytes)

    def start_upload(
        self,
        session: Session,
        owner_id: uuid.UUID,
        filename: str,
        data: bytes,
        media_type: str | None,
    ) -> IngestionJob:
        job = self.engine.start_document_ingestion(
            filename, data, media_type, str(owner_id)
        )
        return self._record_job(session, owner_id, job, "upload")

    def start_youtube(
        self,
        session: Session,
        owner_id: uuid.UUID,
        reference: str,
        languages: tuple[str, ...],
    ) -> IngestionJob:
        job = self.engine.start_youtube_ingestion(reference, languages, str(owner_id))
        return self._record_job(session, owner_id, job, "youtube")

    def _record_job(
        self, session: Session, owner_id: uuid.UUID, job: IngestionJob, kind: str
    ) -> IngestionJob:
        record = IngestionJobRecord(id=job.id, owner_id=owner_id, kind=kind)
        apply_ingestion_job(record, job)
        session.add(record)
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            self.engine.cancel_ingestion(job.id)
            raise
        try:
            latest = self.engine.get_ingestion(job.id)
        except KeyError:
            return ingestion_job_from_record(record)
        apply_ingestion_job(record, latest)
        if latest.state is JobState.COMPLETED and latest.result is not None:
            self._upsert_document(session, owner_id, latest.result)
        session.commit()
        return latest

    def get_job(
        self, session: Session, owner_id: uuid.UUID, job_id: str
    ) -> IngestionJob:
        record = self._owned_job(session, owner_id, job_id)
        try:
            job = self.engine.get_ingestion(job_id)
        except KeyError:
            return ingestion_job_from_record(record)
        apply_ingestion_job(record, job)
        if job.state is JobState.COMPLETED and job.result is not None:
            self._upsert_document(session, owner_id, job.result)
        session.commit()
        return job

    def cancel_job(
        self, session: Session, owner_id: uuid.UUID, job_id: str
    ) -> IngestionJob:
        self._owned_job(session, owner_id, job_id)
        self.engine.cancel_ingestion(job_id)
        return self.get_job(session, owner_id, job_id)

    def list_documents(
        self, session: Session, owner_id: uuid.UUID
    ) -> tuple[DocumentSource, ...]:
        owner = str(owner_id)
        changed = False
        for source in self.engine.list_documents():
            if str(source.metadata.get("owner_id") or "") == owner:
                self._upsert_document(session, owner_id, source)
                changed = True
        if changed:
            session.commit()
        records = session.scalars(
            select(DocumentRecord)
            .where(DocumentRecord.owner_id == owner_id)
            .order_by(DocumentRecord.created_at, DocumentRecord.id)
        ).all()
        return tuple(source_from_record(record) for record in records)

    def delete_document(
        self, session: Session, owner_id: uuid.UUID, document_id: str
    ) -> None:
        record = session.scalar(
            select(DocumentRecord).where(
                DocumentRecord.id == document_id,
                DocumentRecord.owner_id == owner_id,
            )
        )
        if record is None:
            raise OwnedResourceNotFoundError("Document not found")
        self.engine.remove_document(document_id)
        session.delete(record)
        session.commit()

    @staticmethod
    def _owned_job(
        session: Session, owner_id: uuid.UUID, job_id: str
    ) -> IngestionJobRecord:
        record = session.scalar(
            select(IngestionJobRecord).where(
                IngestionJobRecord.id == job_id,
                IngestionJobRecord.owner_id == owner_id,
            )
        )
        if record is None:
            raise OwnedResourceNotFoundError("Ingestion job not found")
        return record

    @staticmethod
    def _upsert_document(
        session: Session, owner_id: uuid.UUID, source: DocumentSource
    ) -> None:
        source_owner = str(source.metadata.get("owner_id") or "")
        if source_owner != str(owner_id):
            raise OwnedResourceNotFoundError("Document ownership mismatch")
        record = session.get(DocumentRecord, source.id)
        if record is None:
            record = DocumentRecord(id=source.id, owner_id=owner_id)
            session.add(record)
        elif record.owner_id != owner_id:
            raise OwnedResourceNotFoundError("Document ownership mismatch")
        record.name = source.name
        record.media_type = source.media_type
        record.sha256 = source.sha256
        record.index_version = source.index_version
        record.source_type = source.source_type
        record.origin_uri = source.origin_uri
        record.storage_path = str(source.path)
        record.document_metadata = dict(source.metadata)

    def _persist_ingestion_update(self, job: IngestionJob) -> None:
        database = self._database
        if database is None:
            return
        with database.session_factory() as session:
            record = session.get(IngestionJobRecord, job.id)
            if record is None:
                return
            apply_ingestion_job(record, job)
            if job.state is JobState.COMPLETED and job.result is not None:
                self._upsert_document(session, record.owner_id, job.result)
            session.commit()

    def _persist_execution_update(self, job: ExecutionJob) -> None:
        database = self._database
        if database is None:
            return
        with database.session_factory() as session:
            record = session.get(ExecutionJobRecord, job.id)
            if record is None:
                return
            apply_execution_job(record, job)
            session.commit()

    def shutdown(self) -> None:
        ingestion_jobs = getattr(self.engine, "ingestion_jobs", None)
        execution = getattr(self.engine, "execution", None)
        if ingestion_jobs is not None:
            ingestion_jobs.shutdown(wait=False)
        if execution is not None:
            execution.shutdown(wait=False)
