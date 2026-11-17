"""Operational monitoring response contracts."""

from __future__ import annotations

from pydantic import BaseModel

from pydebugger.monitoring import MetricSummary


class MetricSummaryResponse(BaseModel):
    operation: str
    calls: int
    failures: int
    failure_rate: float
    average_latency_ms: float
    p95_latency_ms: float
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    cost_usd: float
    cost_configured: bool

    @classmethod
    def from_summary(cls, summary: MetricSummary) -> MetricSummaryResponse:
        return cls(
            operation=summary.operation,
            calls=summary.calls,
            failures=summary.failures,
            failure_rate=(summary.failures / summary.calls if summary.calls else 0.0),
            average_latency_ms=summary.average_latency_ms,
            p95_latency_ms=summary.p95_latency_ms,
            input_tokens=summary.input_tokens,
            output_tokens=summary.output_tokens,
            embedding_tokens=summary.embedding_tokens,
            cost_usd=summary.cost_usd,
            cost_configured=summary.cost_configured,
        )


class MonitoringSummaryResponse(BaseModel):
    window_seconds: float | None
    total_calls: int
    total_failures: int
    total_cost_usd: float
    cost_fully_configured: bool
    warning: str | None
    operations: list[MetricSummaryResponse]
