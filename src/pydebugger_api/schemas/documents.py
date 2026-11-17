"""Document and ingestion-job API contracts."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from pydebugger.models import DocumentSource, IngestionJob, JobState


class YouTubeIngestionRequest(BaseModel):
    reference: str = Field(min_length=1, max_length=2_048)
    languages: list[str] = Field(
        default_factory=lambda: ["en"], min_length=1, max_length=10
    )


class DocumentResponse(BaseModel):
    id: str
    name: str
    media_type: str
    sha256: str
    index_version: str
    source_type: str
    origin_uri: str | None
    metadata: dict[str, object]

    @classmethod
    def from_source(cls, source: DocumentSource) -> DocumentResponse:
        return cls(
            id=source.id,
            name=source.name,
            media_type=source.media_type,
            sha256=source.sha256,
            index_version=source.index_version,
            source_type=source.source_type,
            origin_uri=source.origin_uri,
            metadata={
                key: value
                for key, value in source.metadata.items()
                if key != "owner_id"
            },
        )


class IngestionJobResponse(BaseModel):
    id: str
    state: JobState
    progress: float
    message: str
    attempt: int
    max_attempts: int
    error: str | None = None
    error_code: str | None = None
    result: DocumentResponse | None = None

    @classmethod
    def from_job(cls, job: IngestionJob) -> IngestionJobResponse:
        return cls(
            id=job.id,
            state=job.state,
            progress=job.progress,
            message=job.message,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            error=job.error,
            error_code=job.error_code,
            result=DocumentResponse.from_source(job.result) if job.result else None,
        )


def source_from_record(record) -> DocumentSource:
    """Convert a persistence record without exposing its local storage path."""

    return DocumentSource(
        id=record.id,
        name=record.name,
        path=Path(record.storage_path),
        media_type=record.media_type,
        sha256=record.sha256,
        index_version=record.index_version,
        source_type=record.source_type,
        origin_uri=record.origin_uri,
        metadata=dict(record.document_metadata),
    )
