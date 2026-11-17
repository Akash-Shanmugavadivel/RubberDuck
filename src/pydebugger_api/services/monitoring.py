"""Read-only aggregation over the existing engine monitoring store."""

from __future__ import annotations

from typing import Protocol

from pydebugger.monitoring import MetricSummary

from ..schemas.monitoring import MetricSummaryResponse, MonitoringSummaryResponse


class MonitorState(Protocol):
    last_error: str | None


class MonitoringEngine(Protocol):
    monitor: MonitorState

    def monitoring_summary(
        self, *, since_seconds: float | None = 86_400
    ) -> tuple[MetricSummary, ...]: ...


class MonitoringAPIService:
    def __init__(self, engine: MonitoringEngine) -> None:
        self.engine = engine

    def summary(self, window_seconds: float | None) -> MonitoringSummaryResponse:
        summaries = self.engine.monitoring_summary(since_seconds=window_seconds)
        operations = [MetricSummaryResponse.from_summary(item) for item in summaries]
        configured = [item.cost_configured for item in operations]
        return MonitoringSummaryResponse(
            window_seconds=window_seconds,
            total_calls=sum(item.calls for item in operations),
            total_failures=sum(item.failures for item in operations),
            total_cost_usd=sum(item.cost_usd for item in operations),
            cost_fully_configured=bool(configured) and all(configured),
            warning=self.engine.monitor.last_error,
            operations=operations,
        )
