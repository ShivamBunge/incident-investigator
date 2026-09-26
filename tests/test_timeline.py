"""Deterministic timeline tests: ordering from timestamps only (spec 8)."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.timeline import build_timeline


def _ev(**kwargs):
    return SimpleNamespace(**kwargs)


def test_timeline_sorted_by_timestamp():
    deploy = _ev(
        evidence_type="deployment",
        raw_payload={},
        observed_at=datetime(2026, 9, 22, 14, 2, tzinfo=timezone.utc),
        summary="deployment: checkout-api v1.5.0 rolled out",
        id="ev_1",
    )
    metric = _ev(
        evidence_type="metric",
        raw_payload={
            "metric": "error_rate",
            "points": [
                {"timestamp": "2026-09-22T13:30:00Z", "value": 0.004},
                {"timestamp": "2026-09-22T14:05:00Z", "value": 0.091},
            ],
        },
        observed_at=None,
        summary="",
        id="ev_2",
    )
    events = build_timeline([deploy, metric])
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)


def test_metric_change_event_cites_evidence():
    metric = _ev(
        evidence_type="metric",
        raw_payload={
            "metric": "error_rate",
            "points": [
                {"timestamp": "2026-09-22T13:30:00Z", "value": 0.004},
                {"timestamp": "2026-09-22T14:00:00Z", "value": 0.006},
                {"timestamp": "2026-09-22T14:05:00Z", "value": 0.091},
            ],
        },
        observed_at=None,
        summary="",
        id="ev_9",
    )
    events = build_timeline([metric])
    change = next(e for e in events if e["kind"] == "metric_change")
    assert change["evidence_id"] == "ev_9"
    assert "0.091" in change["description"]


def test_log_signature_first_occurrence_event():
    logs = _ev(
        evidence_type="log_signature",
        raw_payload={
            "top_signatures": [
                {
                    "signature": "timeouterror: connection pool exhausted",
                    "count": 9,
                    "first_seen": "2026-09-22T14:03:07Z",
                    "last_seen": "2026-09-22T14:24:05Z",
                    "sample": "sqlalchemy.exc.TimeoutError: connection pool exhausted after 30s",
                }
            ]
        },
        observed_at=None,
        summary="",
        id="ev_3",
    )
    events = build_timeline([logs])
    assert len(events) == 1
    assert events[0]["kind"] == "log_signature"
    assert events[0]["evidence_id"] == "ev_3"
    assert "14:03:07" in events[0]["timestamp"].isoformat()