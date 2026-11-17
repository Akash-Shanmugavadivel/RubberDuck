from __future__ import annotations

import time
import uuid
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from pydebugger.execution import ExecutionService
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
from pydebugger_api.models import ExecutionJobRecord, IngestionJobRecord, User
from pydebugger_api.services.documents import DocumentService
from pydebugger_api.services.execution import ExecutionAPIService
from pydebugger_api.services.job_persistence import (
    apply_execution_job,
    apply_ingestion_job,
    execution_job_from_record,
    ingestion_job_from_record,
    recover_interrupted_jobs,
)


class TestDatabase:
    __test__ = False

    def __init__(self, path: Path) -> None:
        self.engine = create_engine(
            f"sqlite+pysqlite:///{path}", connect_args={"check_same_thread": False}
        )
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        User.__table__.create(self.engine)
        IngestionJobRecord.__table__.create(self.engine)
        ExecutionJobRecord.__table__.create(self.engine)


def test_ingestion_job_result_round_trips_through_json_payload() -> None:
    owner_id = uuid.uuid4()
    source = DocumentSource(
        id="upload-1",
        name="lesson.txt",
        path=Path("uploads/upload-1/lesson.txt"),
        media_type="text/plain",
        sha256="a" * 64,
        index_version="index-v1",
        metadata={"owner_id": str(owner_id)},
    )
    job = IngestionJob(
        id="ingestion-1",
        state=JobState.COMPLETED,
        result=source,
        progress=1.0,
        message="Document indexed",
        attempt=1,
        max_attempts=3,
    )
    record = IngestionJobRecord(id=job.id, owner_id=owner_id, kind="upload")

    apply_ingestion_job(record, job)
    restored = ingestion_job_from_record(record)

    assert restored == job


def test_execution_diagnostics_and_test_results_round_trip() -> None:
    owner_id = uuid.uuid4()
    diagnostic = PythonDiagnostic(
        exception_type="ValueError",
        message="bad value",
        line_number=2,
        frames=(TracebackFrame("main.py", 2, "<module>", "raise ValueError()"),),
    )
    result = ExecutionResult(
        execution_id="execution-1",
        exit_code=1,
        diagnostic=diagnostic,
        test_results=(
            ExecutionTestResult(
                name="failure",
                passed=False,
                expected_output="ok",
                actual_output="",
                exit_code=1,
                diagnostic=diagnostic,
            ),
        ),
    )
    job = ExecutionJob(
        id="execution-1",
        state=ExecutionState.FAILED,
        result=result,
        error="ValueError: bad value",
        error_code="execution_failed",
        progress=1.0,
        message="Execution failed",
        attempt=1,
        max_attempts=2,
    )
    record = ExecutionJobRecord(id=job.id, owner_id=owner_id, kind="project")

    apply_execution_job(record, job)
    restored = execution_job_from_record(record)

    assert restored == job


def test_startup_recovery_marks_only_interrupted_jobs_failed(tmp_path: Path) -> None:
    database = TestDatabase(tmp_path / "jobs.sqlite3")
    owner_id = uuid.uuid4()
    with database.session_factory() as session:
        session.add(
            User(id=owner_id, email="student@example.com", password_hash="hash")
        )
        session.add_all(
            [
                IngestionJobRecord(
                    id="ingestion-running",
                    owner_id=owner_id,
                    kind="upload",
                    state=JobState.RUNNING.value,
                    progress=0.5,
                    message="Creating embeddings",
                    attempt=1,
                    max_attempts=3,
                ),
                ExecutionJobRecord(
                    id="execution-retrying",
                    owner_id=owner_id,
                    kind="project",
                    state=JobState.RETRYING.value,
                    progress=0.1,
                    message="Retrying",
                    attempt=1,
                    max_attempts=2,
                ),
                ExecutionJobRecord(
                    id="execution-complete",
                    owner_id=owner_id,
                    kind="single_file",
                    state=JobState.COMPLETED.value,
                    progress=1.0,
                    message="Execution completed",
                    attempt=1,
                    max_attempts=2,
                ),
            ]
        )
        session.commit()

    recovered = recover_interrupted_jobs(database)

    with database.session_factory() as session:
        ingestion = session.get(IngestionJobRecord, "ingestion-running")
        retrying = session.get(ExecutionJobRecord, "execution-retrying")
        completed = session.get(ExecutionJobRecord, "execution-complete")
        assert ingestion is not None
        assert retrying is not None
        assert completed is not None
        assert ingestion.state == JobState.FAILED.value
        assert ingestion.error_code == "worker_restarted"
        assert retrying.state == JobState.FAILED.value
        assert completed.state == JobState.COMPLETED.value
    assert recovered == 2


class BlockingExecutor:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def execute(self, source: str, execution_id: str) -> ExecutionResult:
        self.started.set()
        self.release.wait(timeout=2)
        return ExecutionResult(execution_id=execution_id, stdout="done\n", exit_code=0)

    def cancel(self, execution_id: str) -> bool:
        self.release.set()
        return True


class EngineWithExecution:
    def __init__(self, execution: ExecutionService) -> None:
        self.execution = execution
        self.settings = SimpleNamespace(
            execution_source_limit=100_000,
            upload_limit_bytes=1_024,
        )

    def start_execution(self, source: str) -> ExecutionJob:
        return self.execution.submit(source)

    def get_execution(self, execution_id: str) -> ExecutionJob:
        return self.execution.get(execution_id)

    def cancel_execution(self, execution_id: str) -> bool:
        return self.execution.cancel(execution_id)


def test_worker_listener_persists_terminal_state_without_client_polling(
    tmp_path: Path,
) -> None:
    database = TestDatabase(tmp_path / "listener.sqlite3")
    executor = BlockingExecutor()
    worker = ExecutionService(executor, workers=1, queue_size=0)
    engine = EngineWithExecution(worker)
    DocumentService(engine, database)
    api = ExecutionAPIService(engine)
    owner_id = uuid.uuid4()
    with database.session_factory() as session:
        session.add(
            User(id=owner_id, email="student@example.com", password_hash="hash")
        )
        session.commit()
        job = api.start_single(session, owner_id, "print('done')")
    assert executor.started.wait(timeout=1)

    executor.release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with database.session_factory() as session:
            state = session.scalar(
                select(ExecutionJobRecord.state).where(ExecutionJobRecord.id == job.id)
            )
        if state == JobState.COMPLETED.value:
            break
        time.sleep(0.01)
    worker.shutdown()

    assert state == JobState.COMPLETED.value


def test_completed_result_remains_available_after_worker_state_is_lost(
    tmp_path: Path,
) -> None:
    database = TestDatabase(tmp_path / "restart.sqlite3")
    owner_id = uuid.uuid4()
    persisted_job = ExecutionJob(
        id="execution-complete",
        state=ExecutionState.COMPLETED,
        result=ExecutionResult(
            execution_id="execution-complete", stdout="persisted\n", exit_code=0
        ),
        progress=1.0,
        message="Execution completed",
        attempt=1,
        max_attempts=2,
    )
    with database.session_factory() as session:
        session.add(
            User(id=owner_id, email="student@example.com", password_hash="hash")
        )
        record = ExecutionJobRecord(
            id=persisted_job.id, owner_id=owner_id, kind="single_file"
        )
        apply_execution_job(record, persisted_job)
        session.add(record)
        session.commit()

    class RestartedEngine:
        settings = SimpleNamespace(execution_source_limit=100_000)

        @staticmethod
        def get_execution(execution_id: str) -> ExecutionJob:
            raise KeyError(execution_id)

    api = ExecutionAPIService(RestartedEngine())
    with database.session_factory() as session:
        restored = api.get_job(session, owner_id, persisted_job.id)

    assert restored == persisted_job
