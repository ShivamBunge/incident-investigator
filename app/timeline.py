"""Deterministic timeline construction.

Ordering comes from timestamps only — the LLM never decides event order
(spec Section 8). Every event cites the evidence it was derived from.
"""

from __future__ import annotations

import re
from datetime import datetime

CHANGE_FACTOR = 2.0  # a point is a "change" when |value| >= 2x |baseline|


def _ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def build_timeline(evidences) -> list[dict]:
    """Build timestamp-ordered events from normalized evidence."""
    events: list[dict] = []

    for ev in evidences:
        payload = ev.raw_payload or {}

        if ev.evidence_type == "metric":
            events.extend(_metric_events(ev, payload))
        elif ev.evidence_type == "deployment":
            if ev.observed_at is not None:
                events.append(
                    {
                        "timestamp": ev.observed_at,
                        "kind": "deployment",
                        "description": ev.summary,
                        "evidence_id": ev.id,
                    }
                )
        elif ev.evidence_type == "log_signature" and "top_signatures" in payload:
            for sig in payload.get("top_signatures", []):
                first = _ts(sig.get("first_seen"))
                if first is not None:
                    events.append(
                        {
                            "timestamp": first,
                            "kind": "log_signature",
                            "description": (
                                f"first occurrence of \"{sig.get('sample')}\" "
                                f"(x{sig.get('count')} in window)"
                            ),
                            "evidence_id": ev.id,
                        }
                    )
        elif ev.evidence_type in ("workload_status", "pod_status"):
            if ev.observed_at is not None:
                events.append(
                    {
                        "timestamp": ev.observed_at,
                        "kind": "kubernetes_state",
                        "description": ev.summary,
                        "evidence_id": ev.id,
                    }
                )

    events.sort(key=lambda e: e["timestamp"])
    return events


def _metric_events(ev, payload: dict) -> list[dict]:
    points = payload.get("points") or []
    if len(points) < 2:
        return []

    metric = payload.get("metric", "metric")
    baseline_point = points[0]
    events = [
        {
            "timestamp": _ts(baseline_point["timestamp"]),
            "kind": "metric_baseline",
            "description": f"{metric} baseline {baseline_point['value']} at {baseline_point['timestamp']}",
            "evidence_id": ev.id,
        }
    ]

    baseline = baseline_point["value"]
    if baseline:
        threshold = abs(baseline) * CHANGE_FACTOR
        for point in points[1:]:
            if abs(point["value"]) >= threshold and abs(point["value"]) > abs(baseline):
                events.append(
                    {
                        "timestamp": _ts(point["timestamp"]),
                        "kind": "metric_change",
                        "description": (
                            f"{metric} rose from {baseline} to {point['value']} "
                            f"at {point['timestamp']}"
                        ),
                        "evidence_id": ev.id,
                    }
                )
                break
    return events