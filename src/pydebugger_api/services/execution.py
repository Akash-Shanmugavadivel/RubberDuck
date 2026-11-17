"""Authenticated ownership and validation for sandboxed execution jobs."""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pydebugger.models import ExecutionJob, ExecutionTestCase

from ..models import ExecutionJobRecord
from .documents import OwnedResourceNotFoundError
from .job_persistence import (
    apply_execution_job,
    execution_job_from_record,
)

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class ExecutionSettings(Protocol):
    execution_source_limit: int


class ExecutionEngine(Protocol):
    settings: ExecutionSettings

    def start_execution(self, source: str) -> ExecutionJob: ...

    def start_project_execution(
        self,
        files: dict[str, str],
        entrypoint: str,
        tests: list[ExecutionTestCase] | None = None,
    ) -> ExecutionJob: ...

    def get_execution(self, execution_id: str) -> ExecutionJob: ...

    def cancel_execution(self, execution_id: str) -> bool: ...


class ExecutionAPIService:
    def __init__(self, engine: ExecutionEngine) -> None:
        self.engine = engine

    def start_single(
        self, session: Session, owner_id: uuid.UUID, source: str
    ) -> ExecutionJob:
        self._validate_size(len(source.encode("utf-8")))
        job = self.engine.start_execution(source)
        return self._record_job(session, owner_id, job, "single_file")

    def start_project(
        self,
        session: Session,
        owner_id: uuid.UUID,
        files: dict[str, str],
        entrypoint: str,
        tests: list[ExecutionTestCase],
    ) -> ExecutionJob:
        self._validate_project(files, entrypoint, tests)
        job = self.engine.start_project_execution(files, entrypoint, tests)
        return self._record_job(session, owner_id, job, "project")

    def _validate_project(
        self,
        files: dict[str, str],
        entrypoint: str,
        tests: list[ExecutionTestCase],
    ) -> None:
        if not files or len(files) > 20:
            raise ValueError("Projects must contain between 1 and 20 Python files")
        if len(tests) > 10:
            raise ValueError("Projects support at most 10 test cases")
        normalized: set[str] = set()
        submitted_paths: set[str] = set()
        total_bytes = 0
        for file_name, source in files.items():
            path = PurePosixPath(file_name)
            if (
                path.is_absolute()
                or not path.parts
                or any(part in {"", ".", ".."} for part in path.parts)
                or path.suffix != ".py"
                or any(
                    not self._valid_path_part(part, index == len(path.parts) - 1)
                    for index, part in enumerate(path.parts)
                )
            ):
                raise ValueError(f"Unsafe Python project path: {file_name!r}")
            normalized_path = path.as_posix()
            comparison_key = normalized_path.casefold()
            if comparison_key in normalized:
                raise ValueError(f"Duplicate Python project path: {normalized_path}")
            normalized.add(comparison_key)
            submitted_paths.add(normalized_path)
            total_bytes += len(source.encode("utf-8"))
        if entrypoint not in submitted_paths:
            raise ValueError("Project entrypoint must name a submitted Python file")
        total_bytes += sum(
            len(test.stdin.encode("utf-8")) + len(test.expected_output.encode("utf-8"))
            for test in tests
        )
        if any(not test.name.strip() for test in tests):
            raise ValueError("Every test case must have a name")
        self._validate_size(total_bytes)

    @staticmethod
    def _valid_path_part(part: str, is_file: bool) -> bool:
        candidate = part[:-3] if is_file else part
        return (
            bool(candidate)
            and candidate.isascii()
            and candidate.isidentifier()
            and candidate.upper() not in _WINDOWS_RESERVED_NAMES
        )

    def _validate_size(self, byte_count: int) -> None:
        if byte_count > self.engine.settings.execution_source_limit:
            raise ValueError("Execution source exceeds the configured size limit")

    def _record_job(
        self, session: Session, owner_id: uuid.UUID, job: ExecutionJob, kind: str
    ) -> ExecutionJob:
        record = ExecutionJobRecord(id=job.id, owner_id=owner_id, kind=kind)
        apply_execution_job(record, job)
        session.add(record)
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            self.engine.cancel_execution(job.id)
            raise
        try:
            latest = self.engine.get_execution(job.id)
        except KeyError:
            return execution_job_from_record(record)
        apply_execution_job(record, latest)
        session.commit()
        return latest

    def get_job(
        self, session: Session, owner_id: uuid.UUID, execution_id: str
    ) -> ExecutionJob:
        record = self._owned_job(session, owner_id, execution_id)
        try:
            job = self.engine.get_execution(execution_id)
        except KeyError:
            return execution_job_from_record(record)
        apply_execution_job(record, job)
        session.commit()
        return job

    def cancel_job(
        self, session: Session, owner_id: uuid.UUID, execution_id: str
    ) -> ExecutionJob:
        self._owned_job(session, owner_id, execution_id)
        self.engine.cancel_execution(execution_id)
        return self.get_job(session, owner_id, execution_id)

    @staticmethod
    def _owned_job(
        session: Session, owner_id: uuid.UUID, execution_id: str
    ) -> ExecutionJobRecord:
        record = session.scalar(
            select(ExecutionJobRecord).where(
                ExecutionJobRecord.id == execution_id,
                ExecutionJobRecord.owner_id == owner_id,
            )
        )
        if record is None:
            raise OwnedResourceNotFoundError("Execution job not found")
        return record
