"""MCP contract tests over the mock observability provider (spec 5.2/12):
bounded outputs, window filtering, deterministic results, no arbitrary access.
"""

import pytest

from mcp_observability.provider import MockObservabilityProvider, parse_window

WINDOW_A = ("2026-09-22T13:30:00Z", "2026-09-22T14:30:00Z")
WINDOW_B = ("2026-09-23T13:30:00Z", "2026-09-23T14:30:00Z")


@pytest.fixture(scope="module")
def provider() -> MockObservabilityProvider:
    return MockObservabilityProvider()


def test_error_rate_window_filtered_and_bounded(provider):
    series = provider.get_service_error_rate("checkout-api", *WINDOW_A)
    assert 0 < len(series.points) <= 400
    assert series.points[-1].value > 0.05  # incident spike present in window A


def test_window_isolation_between_scenarios(provider):
    a = provider.get_error_log_summary("checkout-api", *WINDOW_A)
    b = provider.get_error_log_summary("checkout-api", *WINDOW_B)
    a_sigs = {s.signature for s in a.top_signatures}
    b_sigs = {s.signature for s in b.top_signatures}
    assert any("pool" in s for s in a_sigs)
    assert any("payment-service" in s for s in b_sigs)
    assert not any("payment-service" in s for s in a_sigs)


def test_unknown_service_returns_empty_not_error(provider):
    series = provider.get_service_error_rate("no-such-service", *WINDOW_A)
    assert series.points == []


def test_search_results_bounded(provider):
    result = provider.search_logs("checkout-api", "connection pool", *WINDOW_A, limit=5)
    assert len(result.matches) <= 5
    assert result.truncated is True


def test_error_summary_deterministic(provider):
    first = provider.get_error_log_summary("checkout-api", *WINDOW_A)
    second = provider.get_error_log_summary("checkout-api", *WINDOW_A)
    assert first == second


def test_window_validation_rejects_bad_ranges(provider):
    with pytest.raises(ValueError):
        parse_window("2026-09-22T14:30:00Z", "2026-09-22T13:30:00Z")  # start >= end
    with pytest.raises(ValueError):
        parse_window("2026-09-22T00:00:00Z", "2026-09-23T00:00:00Z")  # > 6 hours