"""Smoke test for Phase 4: run one full investigation end-to-end.

Requires OPENROUTER_API_KEY in .env for LLM synthesis; without it the flow
still completes with the deterministic fallback synthesis.

Run from the project root with the venv active:
    python scripts/smoke_investigation.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import InvestigationCreate, TimeRange  # noqa: E402
from app.orchestrator import run_investigation  # noqa: E402


async def main() -> None:
    payload = InvestigationCreate(
        question="Why is checkout-api returning 5xx errors?",
        service="checkout-api",
        time_range=TimeRange(
            start="2026-09-22T13:30:00Z",
            end="2026-09-22T14:30:00Z",
        ),
    )
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        result = await run_investigation(payload, db)
    finally:
        db.close()

    print(f"investigation: {result.investigation_id} status={result.status}")
    print(f"unavailable sources: {result.unavailable_sources or 'none'}")
    print(f"rejected evidence ids: {result.rejected_evidence_ids or 'none'}")
    print(f"\nsummary: {result.summary}")
    print("\nfindings:")
    for f in result.findings:
        print(f"  - {f.statement} (evidence: {f.evidence_ids})")
    print("\nhypotheses:")
    for h in result.hypotheses:
        print(f"  - {h.statement} (confidence {h.confidence}, supporting: {h.supporting_evidence_ids})")
    print("\nrecommendations:")
    for r in result.recommendations:
        print(f"  - {r.statement} (because: {r.reason})")
    print("\nmissing information:")
    for m in result.missing_information:
        print(f"  - {m}")
    print(f"\ntimeline ({len(result.timeline)} events, deterministic order):")
    for e in result.timeline:
        print(f"  {e.timestamp.isoformat()} [{e.kind}] {e.description[:90]}")
    print(f"\nevidence count: {len(result.evidence)}")


if __name__ == "__main__":
    asyncio.run(main())