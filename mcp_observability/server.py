"""Observability MCP server — bounded, read-only tools over deterministic data.

Exposed tools (spec Section 5.2):
    get_service_error_rate
    get_service_latency
    get_recent_deployments
    get_error_log_summary
    search_logs
    get_incident_snapshot   (optional convenience)

Deliberately NOT exposed: run_shell, execute_sql, query_any_url, run_promql,
run_logql. The model never gets arbitrary system access.

Transport: stdio (spawned as a child process by the FastAPI app).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_observability.provider import get_provider

mcp = MCPServer("observability")
_provider = get_provider()


@mcp.tool()
def get_service_error_rate(service: str, start: str, end: str) -> dict:
    """Error-rate time series for a service within a bounded time window.

    Args:
        service: Service name, e.g. checkout-api
        start: ISO-8601 UTC start timestamp, e.g. 2026-09-22T13:30:00Z
        end: ISO-8601 UTC end timestamp
    """
    return _provider.get_service_error_rate(service, start, end).model_dump(mode="json")


@mcp.tool()
def get_service_latency(service: str, start: str, end: str) -> dict:
    """p99 latency (ms) time series for a service within a bounded time window.

    Args:
        service: Service name, e.g. checkout-api
        start: ISO-8601 UTC start timestamp
        end: ISO-8601 UTC end timestamp
    """
    return _provider.get_service_latency(service, start, end).model_dump(mode="json")


@mcp.tool()
def get_recent_deployments(service: str, start: str, end: str) -> dict:
    """Recent deployments of a service: in-window rollouts plus rollouts up to
    7 days before the window end.

    Args:
        service: Service name
        start: ISO-8601 UTC start timestamp
        end: ISO-8601 UTC end timestamp
    """
    return _provider.get_recent_deployments(service, start, end).model_dump(mode="json")


@mcp.tool()
def get_error_log_summary(service: str, start: str, end: str) -> dict:
    """Aggregated error/warn log summary: counts and top normalized signatures.

    Args:
        service: Service name
        start: ISO-8601 UTC start timestamp
        end: ISO-8601 UTC end timestamp
    """
    return _provider.get_error_log_summary(service, start, end).model_dump(mode="json")


@mcp.tool()
def search_logs(service: str, query: str, start: str, end: str, limit: int = 20) -> dict:
    """Case-insensitive substring search over log messages, bounded results.

    Args:
        service: Service name
        query: Substring to search for, e.g. "connection pool"
        start: ISO-8601 UTC start timestamp
        end: ISO-8601 UTC end timestamp
        limit: Max lines to return (1-50)
    """
    return _provider.search_logs(service, query, start, end, limit).model_dump(mode="json")


@mcp.tool()
def get_incident_snapshot(service: str, start: str, end: str) -> dict:
    """Convenience bundle: error rate + latency + deployments + error summary.

    Args:
        service: Service name
        start: ISO-8601 UTC start timestamp
        end: ISO-8601 UTC end timestamp
    """
    error_rate = _provider.get_service_error_rate(service, start, end)
    latency = _provider.get_service_latency(service, start, end)
    deployments = _provider.get_recent_deployments(service, start, end)
    summary = _provider.get_error_log_summary(service, start, end)
    return IncidentSnapshot(
        service=service,
        error_rate=error_rate,
        latency=latency,
        deployments=deployments,
        error_log_summary=summary,
    ).model_dump(mode="json")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()