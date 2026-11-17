"""Bounded background processing with observable, failure-safe job states."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import BoundedSemaphore, Event, Lock

from .models import DocumentSource, IngestionJob, JobState


class JobQueueFullError(RuntimeError):
    """Raised when bounded background capacity has been exhausted."""


class JobCancelledError(RuntimeError):
    """Raised cooperatively before an ingestion operation commits."""


class JobTimeoutError(TimeoutError):
    """Raised when an ingestion deadline is reached before commit."""


ProgressReporter = Callable[[float, str], None]
IngestionHandler = Callable[..., DocumentSource]


@dataclass
class _MutableIngestionJob:
    state: JobState
    max_attempts: int
    cancel_event: Event
    result: DocumentSource | None = None
    error: str | None = None
    error_code: str | None = None
    progress: float = 0.0
    message: str = "Queued"
    attempt: int = 0


class IngestionJobService:
    """Run ingestion in a bounded pool with cooperative timeout and retries."""

    def __init__(
        self,
        handler: IngestionHandler,
        *,
        workers: int = 2,
        queue_size: int = 8,
        timeout_seconds: float = 120.0,
        max_attempts: int = 3,
        retryable: Callable[[Exception], bool] | None = None,
    ) -> None:
        self._handler = handler
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._retryable = retryable or (lambda error: isinstance(error, OSError))
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="pydebugger-ingestion"
        )
        self._capacity = BoundedSemaphore(workers + queue_size)
        self._jobs: dict[str, _MutableIngestionJob] = {}
        self._lock = Lock()
        self._listener: Callable[[IngestionJob], None] | None = None

    def set_listener(self, listener: Callable[[IngestionJob], None] | None) -> None:
        self._listener = listener

    def submit(
        self, filename: str, data: bytes, declared_media_type: str | None = None
    ) -> IngestionJob:
        return self._submit(filename, data, declared_media_type, None)

    def submit_scoped(
        self,
        filename: str,
        data: bytes,
        declared_media_type: str | None,
        scope: str,
    ) -> IngestionJob:
        return self._submit(filename, data, declared_media_type, scope)

    def _submit(
        self,
        filename: str,
        data: bytes,
        declared_media_type: str | None,
        scope: str | None,
    ) -> IngestionJob:
        if not self._capacity.acquire(blocking=False):
            raise JobQueueFullError(
                "The ingestion queue is full. Wait for an active upload to finish and retry."
            )
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = _MutableIngestionJob(
                JobState.QUEUED, self._max_attempts, Event()
            )
        try:
            self._executor.submit(
                self._run, job_id, filename, data, declared_media_type, scope
            )
        except Exception:
            self._capacity.release()
            with self._lock:
                self._jobs.pop(job_id, None)
            raise
        job = self.get(job_id)
        self._notify(job_id)
        return job

    def get(self, job_id: str) -> IngestionJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Unknown ingestion job: {job_id}")
            return IngestionJob(
                id=job_id,
                state=job.state,
                result=job.result,
                error=job.error,
                error_code=job.error_code,
                progress=job.progress,
                message=job.message,
                attempt=job.attempt,
                max_attempts=job.max_attempts,
            )

    def cancel(self, job_id: str) -> bool:
        cancelled = False
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in {
                JobState.QUEUED,
                JobState.RUNNING,
                JobState.RETRYING,
            }:
                return False
            job.cancel_event.set()
            cancelled = True
            if job.state is JobState.QUEUED:
                job.state = JobState.CANCELLED
                job.progress = 1.0
                job.message = "Cancelled before ingestion started"
                job.error_code = "cancelled"
            else:
                job.message = "Cancellation requested"
        if cancelled:
            self._notify(job_id)
        return cancelled

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _run(
        self,
        job_id: str,
        filename: str,
        data: bytes,
        declared_media_type: str | None,
        scope: str | None,
    ) -> None:
        deadline = time.monotonic() + self._timeout_seconds
        try:
            for attempt in range(1, self._max_attempts + 1):
                with self._lock:
                    job = self._jobs[job_id]
                    if job.cancel_event.is_set():
                        job.state = JobState.CANCELLED
                        job.message = "Ingestion cancelled"
                        job.error_code = "cancelled"
                        return
                    job.state = JobState.RUNNING
                    job.attempt = attempt
                    job.message = "Starting ingestion"
                self._notify(job_id)
                try:
                    arguments = (
                        filename,
                        data,
                        declared_media_type,
                        lambda progress, message: self._report(
                            job_id, progress, message
                        ),
                        deadline,
                        job.cancel_event,
                    )
                    result = (
                        self._handler(*arguments)
                        if scope is None
                        else self._handler(*arguments, scope)
                    )
                    with self._lock:
                        job = self._jobs[job_id]
                        job.state = JobState.COMPLETED
                        job.result = result
                        job.progress = 1.0
                        job.message = "Document indexed"
                        job.error = None
                        job.error_code = None
                    return
                except JobCancelledError:
                    self._finish_failure(
                        job_id, JobState.CANCELLED, "cancelled", "Ingestion cancelled"
                    )
                    return
                except JobTimeoutError as error:
                    self._finish_failure(
                        job_id, JobState.TIMED_OUT, "ingestion_timeout", str(error)
                    )
                    return
                except Exception as error:  # noqa: BLE001 - job boundary records failures
                    can_retry = (
                        attempt < self._max_attempts
                        and time.monotonic() < deadline
                        and self._retryable(error)
                    )
                    if not can_retry:
                        self._finish_failure(
                            job_id,
                            JobState.FAILED,
                            self._error_code(error),
                            self._useful_error(error),
                        )
                        return
                    with self._lock:
                        job = self._jobs[job_id]
                        job.state = JobState.RETRYING
                        job.message = (
                            f"Attempt {attempt} failed; retrying "
                            f"({attempt + 1}/{self._max_attempts})"
                        )
                    self._notify(job_id)
                    if job.cancel_event.wait(min(0.25 * attempt, 1.0)):
                        self._finish_failure(
                            job_id,
                            JobState.CANCELLED,
                            "cancelled",
                            "Ingestion cancelled",
                        )
                        return
        finally:
            self._capacity.release()
            self._notify(job_id)

    def _report(self, job_id: str, progress: float, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.state in {JobState.RUNNING, JobState.RETRYING}:
                job.progress = max(job.progress, min(0.99, max(0.0, progress)))
                job.message = message
        self._notify(job_id)

    def _notify(self, job_id: str) -> None:
        listener = self._listener
        if listener is None:
            return
        try:
            listener(self.get(job_id))
        except Exception:  # noqa: BLE001 - observers cannot break worker state
            return

    def _finish_failure(
        self, job_id: str, state: JobState, code: str, message: str
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.state = state
            job.progress = 1.0
            job.error_code = code
            job.error = message
            job.message = message

    @staticmethod
    def _error_code(error: Exception) -> str:
        name = type(error).__name__
        mapping = {
            "IngestionError": "invalid_document",
            "RetrievalError": "indexing_failed",
            "EmbeddingMismatchError": "embedding_mismatch",
        }
        return mapping.get(name, "ingestion_failed")

    @staticmethod
    def _useful_error(error: Exception) -> str:
        message = str(error).strip()
        return message if message else f"Ingestion failed ({type(error).__name__})"
