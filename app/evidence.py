"""Normalize MCP tool results into Evidence rows (spec Section 8, step 5).

All summaries here are deterministic calculations over returned data —
derived findings, never model-generated.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db import Evidence, new_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _evidence(
    investigation_id: str,
    *,
    source_type: str,
    evidence_type: str,
    observed_at: datetime | None,
    summary: str,
    raw_payload: dict,
    source_locator: dict,
) -> Evidence:
    return Evidence(
        id=new_id("ev"),
        investigation_id=investigation_id,
        source_type=source_type,
        evidence_type=evidence_type,
        observed_at=observed_at,
        summary=summary,
        raw_payload=raw_payload,
        source_locator=source_locator,
    )


def metric_evidence(investigation_id: str, series: dict, tool: str) -> Evidence:
    """Normalize a MetricSeries result into one metric Evidence row."""
    points = series.get("points", [])
    metric = series.get("metric", "unknown")
    service = series.get("service", "unknown")
    if not points:
        summary = f"{metric} for {service}: no data points in the requested window"
        observed_at = None
    else:
        first, last = points[0], points[-1]
        peak = max(points, key=lambda p: p["value"])
        summary = (
            f"{metric} for {service}: {len(points)} points from {first['timestamp']} "
            f"to {last['timestamp']}; first={first['value']}, last={last['value']}, "
            f"peak={peak['value']} at {peak['timestamp']}"
        )
        observed_at = _parse_ts(last["timestamp"])
    return _evidence(
        investigation_id,
        source_type="observability",
        evidence_type="metric",
        observed_at=observed_at,
        summary=summary,
        raw_payload=series,
        source_locator={"server": "observability", "tool": tool, "service": service_of(series)},
    )


def deployments_evidence(investigation_id: str, result: dict, tool: str) -> list[Evidence]:
    """One Evidence row per deployment record."""
    rows = []
    for record in result.get("deployments", []):
        summary = (
            f"deployment: {record.get('service')} {record.get('version')}"
            + (f" (previous {record['previous_version']})" if record.get("previous_version") else "")
            + f" rolled out at {record.get('deployed_at')}"
            + (f", revision {record['revision']}" if record.get("revision") else "")
        )
        rows.append(
            _evidence(
                investigation_id,
                source_type="observability",
                evidence_type="deployment",
                observed_at=_parse_ts(record.get("deployed_at")),
                summary=summary,
                raw_payload=record,
                source_locator={
                    "server": "observability",
                    "tool": tool,
                    "service": result.get("service"),
                },
            )
        )
    if not rows:
        rows.append(
            _evidence(
                investigation_id,
                source_type="observability",
                evidence_type="deployment",
                observed_at=None,
                summary=f"no deployments found for {result.get('service')} in the recent window",
                raw_payload=result,
                source_locator={"server": "observability", "tool": tool},
            )
        )
    return rows


def log_summary_evidence(investigation_id: str, summary: dict, tool: str) -> Evidence:
    """Normalize a LogSummary result into one log_signature Evidence row."""
    sig_texts = [
        f"x{sig['count']} \"{sig['sample']}\" (first {sig['first_seen']}, last {sig['last_seen']})"
        for sig in summary.get("top_signatures", [])
    ]
    text = (
        f"error log summary for {summary.get('service')} "
        f"({summary.get('window_start')} to {summary.get('window_end')}): "
        f"{summary.get('total_lines')} lines, {summary.get('error_count')} errors, "
        f"{summary.get('warn_count')} warns"
    )
    if sig_texts:
        text += "; top signatures: " + "; ".join(sig_texts)
    return _evidence(
        investigation_id,
        source_type="observability",
        evidence_type="log_signature",
        observed_at=_parse_ts(summary.get("window_end")),
        summary=text,
        raw_payload=summary,
        source_locator={
            "server": "observability",
            "tool": tool,
            "service": summary.get("service"),
        },
    )


def log_search_evidence(investigation_id: str, result: dict, tool: str) -> Evidence:
    """Normalize a SearchLogsResult into one log_signature Evidence row."""
    matches = result.get("matches", [])
    if matches:
        first_ts = matches[0]["timestamp"]
        last_ts = matches[-1]["timestamp"]
        sample = matches[0]["message"]
        text = (
            f"log search \"{result.get('query')}\" for {result.get('service')}: "
            f"{len(matches)} matches from {first_ts} to {last_ts}"
            + (" (truncated)" if result.get("truncated") else "")
            + f"; sample: \"{sample}\""
        )
        observed_at = _parse_ts(last_ts)
    else:
        text = f"log search \"{result.get('query')}\" for {result.get('service')}: 0 matches"
        observed_at = None
    return _evidence(
        investigation_id,
        source_type="observability",
        evidence_type="log_signature",
        observed_at=observed_at,
        summary=text,
        raw_payload=result,
        source_locator={
            "server": "observability",
            "tool": tool,
            "service": result.get("service"),
            "query": result.get("query"),
        },
    )


def workload_summary_evidence(investigation_id: str, result: dict, tool: str) -> Evidence:
    """Normalize a Kubernetes workload summary into one workload_status row."""
    pods_text = ", ".join(
        f"{p.get('name')} ({p.get('phase')}, ready={p.get('ready')}, restarts={p.get('restart_count')})"
        for p in result.get("pods", [])
    )
    warnings = result.get("warning_events") or []
    warn_text = "; ".join(str(w.get("reason")) for w in warnings) if warnings else "none"
    summary = (
        f"kubernetes workload {result.get('service')} in {result.get('namespace')}: "
        f"{result.get('ready_replicas')}/{result.get('desired_replicas')} replicas ready "
        f"({result.get('available_replicas')} available), image {result.get('image')}; "
        f"pods: {pods_text or 'none'}; warning events: {warn_text}"
    )
    return _evidence(
        investigation_id,
        source_type="kubernetes",
        evidence_type="workload_status",
        observed_at=_now(),
        summary=summary,
        raw_payload=result,
        source_locator={"server": "kubernetes", "tool": tool, "service": result.get("service")},
    )


def pod_status_evidence(investigation_id: str, result: dict, tool: str) -> Evidence:
    """Normalize per-pod status into one pod_status row."""
    pods_text = "; ".join(
        f"{p.get('name')}: phase={p.get('phase')}, ready={p.get('ready')}, "
        f"restarts={p.get('restart_count')}"
        + (f", waiting={p['waiting_reason']}" if p.get("waiting_reason") else "")
        + (
            f", last_termination={p['last_termination_reason']}"
            if p.get("last_termination_reason")
            else ""
        )
        for p in result.get("pods", [])
    )
    summary = f"kubernetes pods for {result.get('service')}: {pods_text or 'none found'}"
    return _evidence(
        investigation_id,
        source_type="kubernetes",
        evidence_type="pod_status",
        observed_at=_now(),
        summary=summary,
        raw_payload=result,
        source_locator={"server": "kubernetes", "tool": tool, "service": result.get("service")},
    )


def k8s_deployments_evidence(investigation_id: str, result: dict, tool: str) -> Evidence:
    """Normalize Kubernetes deployment state into one deployment row."""
    rs_text = "; ".join(
        f"rev {rs.get('revision')} image {rs.get('image')} created {rs.get('created_at')}"
        for rs in result.get("replica_sets", [])
    )
    summary = (
        f"kubernetes deployment {result.get('service')}: current {result.get('current_version')}, "
        f"revision {result.get('revision')}, rollout {result.get('rollout_timestamp')}, "
        f"replicas {result.get('replica_status')}; recent replica sets: {rs_text or 'none'}"
    )
    return _evidence(
        investigation_id,
        source_type="kubernetes",
        evidence_type="deployment",
        observed_at=_now(),
        summary=summary,
        raw_payload=result,
        source_locator={"server": "kubernetes", "tool": tool, "service": result.get("service")},
    )


def rag_chunk_evidence(investigation_id: str, chunk) -> Evidence:
    """Normalize a retrieved RAG chunk into a citable document evidence row."""
    evidence_type = {
        "runbook": "runbook_chunk",
        "postmortem": "postmortem_chunk",
    }.get(chunk.document_type, "runbook_chunk")
    heading = f" > {chunk.heading}" if chunk.heading else ""
    excerpt = chunk.content[:400]
    summary = (
        f"{chunk.document_type} \"{chunk.document_title}\"{heading} "
        f"(similarity {chunk.score}): {excerpt}"
    )
    return _evidence(
        investigation_id,
        source_type="rag_document",
        evidence_type=evidence_type,
        observed_at=None,
        summary=summary,
        raw_payload={
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "title": chunk.document_title,
            "document_type": chunk.document_type,
            "heading": chunk.heading,
            "content": chunk.content,
            "score": chunk.score,
        },
        source_locator={
            "server": "rag",
            "document_id": chunk.document_id,
            "chunk_id": chunk.chunk_id,
        },
    )


def service_of(series: dict) -> str:
    return series.get("service", "unknown")


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))