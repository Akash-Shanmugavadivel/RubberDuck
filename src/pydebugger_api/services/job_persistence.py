"""Serialization and recovery for durable background-job state."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from pydebugger.models import (
    DocumentSource,
    ExecutionJob,
    ExecutionResult,
    ExecutionState,
    ExecutionTestResult,
    IngestionJob,
    JobState,
    PythonDiagnostic,
    TracebackFrame,
)

from ..database import Database
from ..models import ExecutionJobRecord, IngestionJobRecord

ACTIVE_STATES = {
    JobState.QUEUED.value,
    JobState.RUNNING.value,
    JobState.RETRYING.value,
}


def apply_ingestion_job(record: IngestionJobRecord, job: IngestionJob) -> None:
    record.state = job.state.value
    record.result_payload = _source_payload(job.result) if job.result else None
    record.error = job.error
    record.error_code = job.error_code
    record.progress = job.progress
    record.message = job.message
    record.attempt = job.attempt
    record.max_attempts = job.max_attempts


def ingestion_job_from_record(record: IngestionJobRecord) -> IngestionJob:
    return IngestionJob(
        id=record.id,
        state=JobState(record.state),
        result=_source_from_payload(record.result_payload),
        error=record.error,
        error_code=record.error_code,
        progress=record.progress,
        message=record.message,
        attempt=record.attempt,
        max_attempts=record.max_attempts,
    )


def apply_execution_job(record: ExecutionJobRecord, job: ExecutionJob) -> None:
    record.state = job.state.value
    record.result_payload = asdict(job.result) if job.result else None
    record.error = job.error
    record.error_code = job.error_code
    record.progress = job.progress
    record.message = job.message
    record.attempt = job.attempt
    record.max_attempts = job.max_attempts


def execution_job_from_record(record: ExecutionJobRecord) -> ExecutionJob:
    return ExecutionJob(
        id=record.id,
        state=ExecutionState(record.state),
        result=_execution_result_from_payload(record.result_payload),
        error=record.error,
        error_code=record.error_code,
        progress=record.progress,
        message=record.message,
        attempt=record.attempt,
        max_attempts=record.max_attempts,
    )


def recover_interrupted_jobs(database: Database) -> int:
    """Mark work interrupted by process restart as a stable terminal failure."""

    recovered = 0
    for model in (IngestionJobRecord, ExecutionJobRecord):
        try:
            with database.session_factory() as session:
                result = session.execute(
                    update(model)
                    .where(model.state.in_(ACTIVE_STATES))
                    .values(
                        state=JobState.FAILED.value,
                        progress=1.0,
                        message="Worker restarted before the job completed",
                        error="Worker restarted before the job completed",
                        error_code="worker_restarted",
                    )
                )
                recovered += int(result.rowcount or 0)
                session.commit()
        except SQLAlchemyError:
            # Readiness and migrations report database problems separately.
            continue
    return recovered


def _source_payload(source: DocumentSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "path": str(source.path),
        "media_type": source.media_type,
        "sha256": source.sha256,
        "index_version": source.index_version,
        "source_key": source.source_key,
        "source_type": source.source_type,
        "origin_uri": source.origin_uri,
        "metadata": source.metadata,
    }


def _source_from_payload(payload: dict[str, Any] | None) -> DocumentSource | None:
    if payload is None:
        return None
    return DocumentSource(
        id=str(payload["id"]),
        name=str(payload["name"]),
        path=Path(str(payload["path"])),
        media_type=str(payload["media_type"]),
        sha256=str(payload["sha256"]),
        index_version=str(payload.get("index_version") or ""),
        source_key=str(payload["source_key"]) if payload.get("source_key") else None,
        source_type=str(payload.get("source_type") or "upload"),
        origin_uri=str(payload["origin_uri"]) if payload.get("origin_uri") else None,
        metadata=dict(payload.get("metadata") or {}),
    )


def _diagnostic_from_payload(payload: dict[str, Any] | None) -> PythonDiagnostic | None:
    if payload is None:
        return None
    frames = tuple(TracebackFrame(**frame) for frame in payload.get("frames") or [])
    values = {key: value for key, value in payload.items() if key != "frames"}
    return PythonDiagnostic(**values, frames=frames)


def _test_result_from_payload(payload: dict[str, Any]) -> ExecutionTestResult:
    values = {key: value for key, value in payload.items() if key != "diagnostic"}
    return ExecutionTestResult(
        **values,
        diagnostic=_diagnostic_from_payload(payload.get("diagnostic")),
    )


def _execution_result_from_payload(
    payload: dict[str, Any] | None,
) -> ExecutionResult | None:
    if payload is None:
        return None
    excluded = {"diagnostic", "test_results"}
    values = {key: value for key, value in payload.items() if key not in excluded}
    return ExecutionResult(
        **values,
        diagnostic=_diagnostic_from_payload(payload.get("diagnostic")),
        test_results=tuple(
            _test_result_from_payload(item)
            for item in payload.get("test_results") or []
        ),
    )
