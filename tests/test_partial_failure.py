"""Partial-failure handling: broken MCP servers must not fail the investigation
(spec Section 12: one failed tool must not fail the entire investigation)."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db import SessionLocal, engine
from app.models import InvestigationCreate, TimeRange
from sqlalchemy import text


def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="postgres not reachable")


def _payload() -> InvestigationCreate:
    return InvestigationCreate(
        question="Why is checkout-api returning 5xx errors?",
        service="checkout-api",
        time_range=TimeRange(start="2026-09-22T13:30:00Z", end="2026-09-22T14:30:00Z"),
    )


def test_broken_mcp_servers_still_complete(monkeypatch):
    from app.orchestrator import run_investigation

    monkeypatch.setattr(
        settings, "obs_mcp_server_cmd", "python -m mcp_observability.does_not_exist"
    )
    monkeypatch.setattr(
        settings, "k8s_mcp_server_cmd", "python -m mcp_kubernetes.does_not_exist"
    )

    db = SessionLocal()
    try:
        result = asyncio.run(run_investigation(_payload(), db))
    finally:
        db.close()

    assert result.status == "completed"
    assert any("observability" in s for s in result.unavailable_sources)
    assert any("kubernetes" in s for s in result.unavailable_sources)
    # RAG retrieval is local, so document evidence is still collected.
    assert any(ev.evidence_type in ("runbook_chunk", "postmortem_chunk") for ev in result.evidence)
    # Degraded synthesis is explicit, never a crash.
    assert result.summary


def test_partial_failure_observability_only(monkeypatch):
    """Kubernetes healthy + observability broken -> k8s evidence still collected."""
    from app.orchestrator import run_investigation

    monkeypatch.setattr(
        settings, "obs_mcp_server_cmd", "python -m mcp_observability.does_not_exist"
    )

    db = SessionLocal()
    try:
        result = asyncio.run(run_investigation(_payload(), db))
    finally:
        db.close()

    assert result.status == "completed"
    assert any("observability" in s for s in result.unavailable_sources)
    assert any(ev.source_type == "kubernetes" for ev in result.evidence)