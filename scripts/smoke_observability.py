"""Smoke test for Phase 2a/2b: provider over scenario data + MCP tool surface.

Run from the project root with the venv active:
    python scripts/smoke_observability.py
"""

from mcp_observability.provider import MockObservabilityProvider

WINDOW = ("2026-09-22T13:30:00Z", "2026-09-22T14:30:00Z")


def main() -> None:
    provider = MockObservabilityProvider()

    error_rate = provider.get_service_error_rate("checkout-api", *WINDOW)
    print(f"error_rate points: {len(error_rate.points)}")
    print(f"  first: {error_rate.points[0]}")
    print(f"  last:  {error_rate.points[-1]}")

    latency = provider.get_service_latency("checkout-api", *WINDOW)
    print(f"latency points: {len(latency.points)} (peak {max(p.value for p in latency.points)}ms)")

    deployments = provider.get_recent_deployments("checkout-api", *WINDOW)
    print(f"deployments: {[(d.version, d.deployed_at.isoformat()) for d in deployments.deployments]}")

    summary = provider.get_error_log_summary("checkout-api", *WINDOW)
    print(f"log summary: total={summary.total_lines} errors={summary.error_count} warns={summary.warn_count}")
    for sig in summary.top_signatures:
        print(f"  x{sig.count} {sig.signature[:70]}")

    search = provider.search_logs("checkout-api", "connection pool", *WINDOW)
    print(f"search 'connection pool': {len(search.matches)} matches, truncated={search.truncated}")

    # Window isolation: scenario B data must not leak into scenario A's window.
    b_window = ("2026-09-23T13:30:00Z", "2026-09-23T14:30:00Z")
    b_summary = provider.get_error_log_summary("checkout-api", *b_window)
    top = b_summary.top_signatures[0].signature if b_summary.top_signatures else "<none>"
    print(f"scenario B window top signature: {top[:70]}")

    # Unknown service returns empty results (deterministic, no error).
    empty = provider.get_service_error_rate("unknown-service", *WINDOW)
    print(f"unknown service points: {len(empty.points)} (expect 0)")


if __name__ == "__main__":
    main()