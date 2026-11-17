"""Isolated Python execution API contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pydebugger.models import ExecutionJob, ExecutionState


class SingleFileExecutionRequest(BaseModel):
    source: str = Field(min_length=1, max_length=1_000_000)


class ExecutionTestCaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    stdin: str = Field(default="", max_length=100_000)
    expected_output: str = Field(default="", max_length=100_000)


class ProjectExecutionRequest(BaseModel):
    files: dict[str, str] = Field(min_length=1, max_length=20)
    entrypoint: str = Field(default="main.py", min_length=1, max_length=512)
    tests: list[ExecutionTestCaseRequest] = Field(default_factory=list, max_length=10)


class TracebackFrameResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    file_name: str
    line_number: int
    function_name: str
    source_line: str | None = None


class DiagnosticResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exception_type: str
    message: str
    file_name: str
    line_number: int | None = None
    column_number: int | None = None
    end_line_number: int | None = None
    end_column_number: int | None = None
    source_line: str | None = None
    frames: list[TracebackFrameResponse]


class ExecutionTestResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    passed: bool
    expected_output: str
    actual_output: str
    stderr: str
    exit_code: int | None
    duration_seconds: float
    diagnostic: DiagnosticResponse | None


class ExecutionResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str | None
    stdout: str
    stderr: str
    exit_code: int | None
    duration_seconds: float
    timed_out: bool
    cancelled: bool
    resource_limit_exceeded: bool
    truncated: bool
    disabled_reason: str | None
    diagnostic: DiagnosticResponse | None
    traceback: str
    test_results: list[ExecutionTestResultResponse]


class ExecutionJobResponse(BaseModel):
    id: str
    state: ExecutionState
    result: ExecutionResultResponse | None = None
    error: str | None = None
    error_code: str | None = None
    progress: float
    message: str
    attempt: int
    max_attempts: int

    @classmethod
    def from_job(cls, job: ExecutionJob) -> ExecutionJobResponse:
        return cls(
            id=job.id,
            state=job.state,
            result=(
                ExecutionResultResponse.model_validate(job.result)
                if job.result is not None
                else None
            ),
            error=job.error,
            error_code=job.error_code,
            progress=job.progress,
            message=job.message,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
        )
