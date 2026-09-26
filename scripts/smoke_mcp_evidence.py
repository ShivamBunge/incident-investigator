"""Smoke test for Phase 2c: spawn the observability MCP server over stdio,
call bounded tools concurrently, and normalize results into Evidence rows.

Run from the project root with the venv active:
    python scripts/smoke_mcp_evidence.py
"""

import asyncio

from app.config import settings
from app.evidence import (
    deployments_evidence,
    log_search_evidence,
    log_summary_evidence,
    metric_evidence,
)
from app.mcp_client import MCPServer

SERVICE = "checkout-api"
WINDOW = {"start": "2026-09-22T13:30:00Z", "end": "2026-09-22T14:30:00Z"}


async def main() -> None:
    async with MCPServer(settings.obs_mcp_server_cmd, settings.mcp_tool_timeout_seconds) as obs:
        # Independent tool calls execute concurrently.
        error_rate, latency, deployments, summary, search = await asyncio.gather(
            obs.call("get_service_error_rate", {"service": SERVICE, **WINDOW}),
            obs.call("get_service_latency", {"service": SERVICE, **WINDOW}),
            obs.call("get_recent_deployments", {"service": SERVICE, **WINDOW}),
            obs.call("get_error_log_summary", {"service": SERVICE, **WINDOW}),
            obs.call("search_logs", {"service": SERVICE, "query": "connection pool", **WINDOW}),
        )

    evidences = [
        metric_evidence("inv_smoke", error_rate, "get_service_error_rate"),
        metric_evidence("inv_smoke", latency, "get_service_latency"),
        *deployments_evidence("inv_smoke", deployments, "get_recent_deployments"),
        log_summary_evidence("inv_smoke", summary, "get_error_log_summary"),
        log_search_evidence("inv_smoke", search, "search_logs"),
    ]

    print(f"normalized {len(evidences)} evidence rows:")
    for ev in evidences:
        print(f"  [{ev.evidence_type}] {ev.summary}")


if __name__ == "__main__":
    asyncio.run(main())