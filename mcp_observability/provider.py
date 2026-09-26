"""Observability provider abstraction + deterministic mock provider.

The MCP tool contracts (names, arguments, result schemas) stay unchanged when a
real Prometheus/Loki provider replaces the mock (spec Section 5.2).
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

MAX_WINDOW_HOURS = 6.0
MAX_LOG_LINES = 50
MAX_METRIC_POINTS = 400
MAX_SIGNATURES = 5


class MetricPoint(BaseModel):
    timestamp: datetime
    value: float


class MetricSeries(BaseModel):
    service: str
    metric: str
    points: list[MetricPoint]


class DeploymentRecord(BaseModel):
    service: str
    version: str
    deployed_at: datetime
    revision: str | None = None
    previous_version: str | None = None


class DeploymentsResult(BaseModel):
    service: str
    deployments: list[DeploymentRecord]


class LogLine(BaseModel):
    timestamp: datetime
    level: str
    message: str
    service: str


class LogSignature(BaseModel):
    signature: str
    count: int
    first_seen: datetime
    last_seen: datetime
    sample: str


class LogSummary(BaseModel):
    service: str
    window_start: datetime
    window_end: datetime
    total_lines: int
    error_count: int
    warn_count: int
    top_signatures: list[LogSignature]


class SearchLogsResult(BaseModel):
    service: str
    query: str
    matches: list[LogLine]
    truncated: bool


class IncidentSnapshot(BaseModel):
    service: str
    error_rate: MetricSeries
    latency: MetricSeries
    deployments: DeploymentsResult
    error_log_summary: LogSummary


def parse_window(start: str, end: str) -> tuple[datetime, datetime]:
    """Parse and validate a bounded ISO-8601 UTC time window."""
    s = datetime.fromisoformat(start.replace("Z", "+00:00"))
    e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    if s >= e:
        raise ValueError("start must be before end")
    if (e - s) > timedelta(hours=MAX_WINDOW_HOURS):
        raise ValueError(f"time window exceeds {MAX_WINDOW_HOURS} hours")
    return s, e


def _signature(message: str) -> str:
    """Normalize a log message into a stable signature for grouping."""
    normalized = re.sub(r"\d+", "#", message.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:120]


class ObservabilityProvider(ABC):
    """Read-only observability contract. Implementations must be deterministic
    for identical inputs (mock) or map to real backends (Prometheus/Loki later)."""

    @abstractmethod
    def get_service_error_rate(self, service: str, start: str, end: str) -> MetricSeries: ...

    @abstractmethod
    def get_service_latency(self, service: str, start: str, end: str) -> MetricSeries: ...

    @abstractmethod
    def get_recent_deployments(self, service: str, start: str, end: str) -> DeploymentsResult: ...

    @abstractmethod
    def get_error_log_summary(self, service: str, start: str, end: str) -> LogSummary: ...

    @abstractmethod
    def search_logs(
        self, service: str, query: str, start: str, end: str, limit: int = 20
    ) -> SearchLogsResult: ...


class MockObservabilityProvider(ObservabilityProvider):
    """Deterministic provider backed by scenario JSON files in scenarios/."""

    def __init__(self, scenarios_dir: str | Path | None = None) -> None:
        base = Path(scenarios_dir) if scenarios_dir else Path(__file__).parent / "scenarios"
        self._scenarios = []
        for path in sorted(base.glob("*.json")):
            self._scenarios.append(json.loads(path.read_text(encoding="utf-8")))

    def _scenario_logs(self, service: str, start: datetime, end: datetime) -> list[LogLine]:
        lines: list[LogLine] = []
        for scenario in self._scenarios:
            if scenario.get("service") != service:
                continue
            for raw in scenario.get("logs", []):
                line = LogLine.model_validate(raw)
                if start <= line.timestamp <= end:
                    lines.append(line)
        lines.sort(key=lambda l: l.timestamp)
        return lines

    def _metric(self, service: str, metric: str, start: datetime, end: datetime) -> MetricSeries:
        points: list[MetricPoint] = []
        for scenario in self._scenarios:
            if scenario.get("service") != service:
                continue
            for raw in scenario.get("metrics", {}).get(metric, []):
                point = MetricPoint.model_validate(raw)
                if start <= point.timestamp <= end:
                    points.append(point)
        points.sort(key=lambda p: p.timestamp)
        return MetricSeries(service=service, metric=metric, points=points[:MAX_METRIC_POINTS])

    def get_service_error_rate(self, service: str, start: str, end: str) -> MetricSeries:
        s, e = parse_window(start, end)
        return self._metric(service, "error_rate", s, e)

    def get_service_latency(self, service: str, start: str, end: str) -> MetricSeries:
        s, e = parse_window(start, end)
        return self._metric(service, "latency_p99_ms", s, e)

    def get_recent_deployments(self, service: str, start: str, end: str) -> DeploymentsResult:
        s, e = parse_window(start, end)
        records: list[DeploymentRecord] = []
        for scenario in self._scenarios:
            if scenario.get("service") != service:
                continue
            for raw in scenario.get("deployments", []):
                record = DeploymentRecord.model_validate(raw)
                # In-window rollouts, or rollouts up to 7 days before the window
                # (still "recent" from the investigator's point of view).
                if s <= record.deployed_at <= e or (e - timedelta(days=7)) <= record.deployed_at <= e:
                    records.append(record)
        records.sort(key=lambda r: r.deployed_at)
        return DeploymentsResult(service=service, deployments=records)

    def get_error_log_summary(self, service: str, start: str, end: str) -> LogSummary:
        s, e = parse_window(start, end)
        lines = self._scenario_logs(service, s, e)
        errors = [l for l in lines if l.level.upper() == "ERROR"]
        warns = [l for l in lines if l.level.upper() == "WARN"]

        groups: dict[str, list[LogLine]] = {}
        for line in errors + warns:
            groups.setdefault(_signature(line.message), []).append(line)

        ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:MAX_SIGNATURES]
        signatures = [
            LogSignature(
                signature=sig,
                count=len(group),
                first_seen=min(l.timestamp for l in group),
                last_seen=max(l.timestamp for l in group),
                sample=group[0].message,
            )
            for sig, group in ranked
        ]
        return LogSummary(
            service=service,
            window_start=s,
            window_end=e,
            total_lines=len(lines),
            error_count=len(errors),
            warn_count=len(warns),
            top_signatures=signatures,
        )

    def search_logs(
        self, service: str, query: str, start: str, end: str, limit: int = 20
    ) -> SearchLogsResult:
        s, e = parse_window(start, end)
        needle = query.lower().strip()
        matches = [
            line
            for line in self._scenario_logs(service, s, e)
            if needle in line.message.lower()
        ]
        bounded = matches[: min(max(limit, 1), MAX_LOG_LINES)]
        return SearchLogsResult(
            service=service,
            query=query,
            matches=bounded,
            truncated=len(matches) > len(bounded),
        )


def get_provider() -> ObservabilityProvider:
    """Provider factory. v1 ships only the mock; Prometheus/Loki comes later."""
    name = os.environ.get("OBS_PROVIDER", "mock").lower()
    if name == "mock":
        return MockObservabilityProvider()
    raise ValueError(f"Unknown observability provider: {name!r}")