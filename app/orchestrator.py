"""Bounded investigation flow (spec Section 8). No autonomous loop.

Steps:
1. Receive question, validate time window (Pydantic)
2. Collect metric/log evidence through the observability MCP server
3. Collect workload/pod/deployment evidence through the Kubernetes MCP server
4. Normalize all MCP results into Evidence objects
5. Extract dominant observed symptoms
6. Build a focused RAG query
7. Retrieve relevant runbook/postmortem chunks, add as Evidence
8. Build deterministic timeline
9. Ask LLM to produce findings + hypotheses
10. Validate evidence references
11. Return structured result

One failed tool never fails the investigation: failures are recorded as
unavailable sources and the flow continues (spec Section 12).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.citations import validate_citations
from app.config import settings
from app.db import Evidence, Investigation
from app.evidence import (
    deployments_evidence,
    k8s_deployments_evidence,
    log_search_evidence,
    log_summary_evidence,
    metric_evidence,
    pod_status_evidence,
    rag_chunk_evidence,
    workload_summary_evidence,
)
from app.llm import LLMSynthesisError, PROMPT_VERSION, SYSTEM_PROMPT, get_llm_provider
from app.mcp_client import MCPToolError, MCPServer
from app.models import InvestigationCreate, InvestigationResult, SynthesisResult, TimelineEventOut
from app.rag.retrieve import retrieve_chunks
from app.redaction import redact_text
from app.timeline import build_timeline

logger = logging.getLogger(__name__)

MAX_RAG_CHUNKS = 5
LOG_SEARCH_QUERIES = ("error", "timeout")

_STOPWORDS = {
    "after", "the", "a", "an", "at", "in", "for", "with", "by", "on", "from",
    "to", "of", "and", "or", "is", "are", "was", "were", "not", "it", "its",
    "this", "that", "be", "been",
}


async def run_investigation(payload: InvestigationCreate, db: Session) -> InvestigationResult:
    started = datetime.now(timezone.utc)

    investigation = Investigation(
        service=payload.service,
        question=payload.question,
        start_time=payload.time_range.start,
        end_time=payload.time_range.end,
        status="running",
    )
    db.add(investigation)
    db.commit()

    window = {
        "start": payload.time_range.start.isoformat(),
        "end": payload.time_range.end.isoformat(),
    }

    unavailable: list[str] = []

    obs_evidence, obs_failures = await _collect_observability(
        investigation.id, payload.service, window
    )
    unavailable.extend(obs_failures)

    k8s_evidence, k8s_failures = await _collect_kubernetes(investigation.id, payload.service)
    unavailable.extend(k8s_failures)

    evidence: list[Evidence] = obs_evidence + k8s_evidence

    # Symptoms -> focused RAG query -> retrieved chunks as evidence.
    symptoms = _extract_symptoms(evidence)
    rag_query = _build_rag_query(payload.service, payload.question, symptoms)
    logger.info("investigation %s rag query: %s", investigation.id, rag_query)
    chunks = retrieve_chunks(db, rag_query, k=MAX_RAG_CHUNKS, service=payload.service)
    evidence.extend(rag_chunk_evidence(investigation.id, chunk) for chunk in chunks)

    for ev in evidence:
        db.add(ev)
    db.commit()

    # Deterministic timeline: ordering from timestamps only.
    timeline = build_timeline(evidence)

    synthesis, rejected_ids = await _synthesize(payload, evidence, timeline, unavailable)

    result = InvestigationResult(
        investigation_id=investigation.id,
        question=payload.question,
        service=payload.service,
        status="completed",
        summary=synthesis.summary,
        findings=synthesis.findings,
        hypotheses=synthesis.hypotheses,
        recommendations=synthesis.recommendations,
        missing_information=synthesis.missing_information,
        timeline=[TimelineEventOut(**event) for event in timeline],
        evidence=[
            {
                "id": ev.id,
                "source_type": ev.source_type,
                "evidence_type": ev.evidence_type,
                "observed_at": ev.observed_at,
                "summary": ev.summary,
                "source_locator": ev.source_locator,
            }
            for ev in evidence
        ],
        unavailable_sources=unavailable,
        rejected_evidence_ids=rejected_ids,
    )

    investigation.status = "completed"
    investigation.completed_at = datetime.now(timezone.utc)
    investigation.result = result.model_dump(mode="json")
    db.commit()

    logger.info(
        "investigation %s completed in %.1fs (evidence=%d, unavailable=%s, prompt=%s)",
        investigation.id,
        (datetime.now(timezone.utc) - started).total_seconds(),
        len(evidence),
        len(unavailable),
        PROMPT_VERSION,
    )
    return result


# --- Evidence collection -----------------------------------------------------


async def _collect_observability(
    investigation_id: str, service: str, window: dict
) -> tuple[list[Evidence], list[str]]:
    evidences: list[Evidence] = []
    failures: list[str] = []

    try:
        async with MCPServer(
            settings.obs_mcp_server_cmd, settings.mcp_tool_timeout_seconds
        ) as obs:
            calls = {
                "get_service_error_rate": obs.call(
                    "get_service_error_rate", {"service": service, **window}
                ),
                "get_service_latency": obs.call(
                    "get_service_latency", {"service": service, **window}
                ),
                "get_recent_deployments": obs.call(
                    "get_recent_deployments", {"service": service, **window}
                ),
                "get_error_log_summary": obs.call(
                    "get_error_log_summary", {"service": service, **window}
                ),
                **{
                    f"search_logs:{query}": obs.call(
                        "search_logs", {"service": service, "query": query, **window}
                    )
                    for query in LOG_SEARCH_QUERIES
                },
            }
            names = list(calls)
            outcomes = await asyncio.gather(
                *[_safe(name, coro) for name, coro in calls.items()]
            )
    except MCPToolError as exc:
        logger.warning("observability MCP server unavailable: %s", exc)
        return evidences, [f"observability:server ({exc})"]

    for name, (result, error) in zip(names, outcomes):
        if error is not None:
            failures.append(f"observability:{error}")
            continue
        if name == "get_service_error_rate":
            evidences.append(metric_evidence(investigation_id, result, name))
        elif name == "get_service_latency":
            evidences.append(metric_evidence(investigation_id, result, name))
        elif name == "get_recent_deployments":
            evidences.extend(deployments_evidence(investigation_id, result, name))
        elif name == "get_error_log_summary":
            evidences.append(log_summary_evidence(investigation_id, result, name))
        elif name.startswith("search_logs:"):
            evidences.append(log_search_evidence(investigation_id, result, "search_logs"))

    return evidences, failures


async def _collect_kubernetes(
    investigation_id: str, service: str
) -> tuple[list[Evidence], list[str]]:
    evidences: list[Evidence] = []
    failures: list[str] = []

    try:
        async with MCPServer(
            settings.k8s_mcp_server_cmd, settings.mcp_tool_timeout_seconds
        ) as k8s:
            calls = {
                "get_workload_summary": k8s.call("get_workload_summary", {"service": service}),
                "get_pod_status": k8s.call("get_pod_status", {"service": service}),
                "get_recent_deployments": k8s.call(
                    "get_recent_deployments", {"service": service}
                ),
            }
            names = list(calls)
            outcomes = await asyncio.gather(
                *[_safe(name, coro) for name, coro in calls.items()]
            )
    except MCPToolError as exc:
        logger.warning("kubernetes MCP server unavailable: %s", exc)
        return evidences, [f"kubernetes:server ({exc})"]

    for name, (result, error) in zip(names, outcomes):
        if error is not None:
            failures.append(f"kubernetes:{error}")
            continue
        if not result.get("available", False):
            failures.append(f"kubernetes:{name} ({result.get('error', 'unavailable')})")
            continue
        if name == "get_workload_summary":
            evidences.append(workload_summary_evidence(investigation_id, result, name))
        elif name == "get_pod_status":
            evidences.append(pod_status_evidence(investigation_id, result, name))
        elif name == "get_recent_deployments":
            evidences.append(k8s_deployments_evidence(investigation_id, result, name))

    return evidences, failures


async def _safe(name: str, coro):
    try:
        return await coro, None
    except Exception as exc:  # noqa: BLE001 - per-tool isolation
        logger.warning("tool %s failed: %s", name, exc)
        return None, f"{name} ({exc})"


# --- Symptoms / RAG query ------------------------------------------------------


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_symptoms(evidence: list[Evidence]) -> dict:
    signatures: list[str] = []
    changes: list[str] = []
    change_times: list[datetime] = []
    deployments: list[dict] = []
    for ev in evidence:
        payload = ev.raw_payload or {}
        if ev.evidence_type == "log_signature" and "top_signatures" in payload:
            signatures.extend(s["signature"] for s in payload["top_signatures"][:3])
        elif ev.evidence_type == "metric":
            points = payload.get("points") or []
            if len(points) >= 2:
                baseline = points[0]["value"]
                peak = max(points, key=lambda p: p["value"])
                if baseline and abs(peak["value"]) >= abs(baseline) * 2:
                    changes.append(
                        f"{payload.get('metric')} rose from {baseline} to {peak['value']}"
                    )
                    change_ts = _parse_ts(peak.get("timestamp"))
                    if change_ts is not None:
                        change_times.append(change_ts)
        elif ev.evidence_type == "deployment" and payload.get("deployed_at"):
            deployments.append(payload)

    # Deterministic correlation: a rollout shortly before a metric change.
    recent_deployments: list[str] = []
    for deployment in deployments:
        deployed_at = _parse_ts(deployment.get("deployed_at"))
        if deployed_at is None:
            continue
        for change_ts in change_times:
            if timedelta(0) <= (change_ts - deployed_at) <= timedelta(minutes=45):
                recent_deployments.append(str(deployment.get("version") or "unknown"))
                break

    return {
        "signatures": signatures,
        "changes": changes,
        "recent_deployments": recent_deployments,
    }


def _build_rag_query(service: str, question: str, symptoms: dict) -> str:
    words: list[str] = [service]
    for signature in symptoms["signatures"][:2]:
        for word in re.findall(r"[a-zA-Z]+", signature):
            lowered = word.lower()
            if lowered not in _STOPWORDS and lowered not in words:
                words.append(lowered)
    if symptoms.get("recent_deployments"):
        # A rollout closely preceded the degradation — steer retrieval toward
        # the deployment regression runbook.
        words.extend(w for w in ("deployment", "rollout", "regression") if w not in words)
    query = " ".join(words[:12])
    if len(query) < len(service) + 5:
        query = f"{service} {question}"
    return f"{query} runbook"


# --- Synthesis -----------------------------------------------------------------


async def _synthesize(
    payload: InvestigationCreate,
    evidence: list[Evidence],
    timeline: list[dict],
    unavailable: list[str],
) -> tuple[SynthesisResult, list[str]]:
    valid_ids = {ev.id for ev in evidence}

    evidence_lines = "\n".join(f"[{ev.id}] ({ev.evidence_type}) {ev.summary}" for ev in evidence)
    timeline_lines = "\n".join(
        f"{event['timestamp'].isoformat()} {event['kind']}: {event['description']}"
        for event in timeline
    )
    user_prompt = (
        f"Question: {payload.question}\n"
        f"Service: {payload.service}\n"
        f"Time window: {payload.time_range.start.isoformat()} to "
        f"{payload.time_range.end.isoformat()}\n\n"
        f"Deterministic timeline (ordered by timestamp):\n"
        f"{timeline_lines or '(no events)'}\n\n"
        f"Evidence (IDs in brackets are the ONLY valid citations):\n{evidence_lines}\n\n"
        f"Unavailable sources: {', '.join(unavailable) if unavailable else 'none'}\n\n"
        f"Produce the JSON diagnosis now."
    )
    # Treat evidence content as untrusted; redact secrets before external call.
    user_prompt = redact_text(user_prompt)

    try:
        provider = get_llm_provider()
    except LLMSynthesisError as exc:
        return _fallback_synthesis(evidence, str(exc)), []

    try:
        raw = await provider.complete_json(SYSTEM_PROMPT, user_prompt)
        synthesis = SynthesisResult.model_validate(raw)
        usage = getattr(provider, "last_usage", None)
        if usage:
            logger.info(
                "LLM token usage: prompt=%s completion=%s total=%s model=%s prompt_version=%s",
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
                settings.openrouter_model,
                PROMPT_VERSION,
            )
    except (LLMSynthesisError, ValidationError) as exc:
        logger.warning("LLM synthesis failed: %s", exc)
        return _fallback_synthesis(evidence, f"LLM synthesis failed: {exc}"), []

    return validate_citations(synthesis, {ev.id for ev in evidence})


def _fallback_synthesis(evidence: list[Evidence], reason: str) -> SynthesisResult:
    """Deterministic degraded result when the LLM is unavailable or invalid."""
    symptoms = _extract_symptoms(evidence)
    observed = "; ".join(symptoms["changes"] + symptoms["signatures"][:2])
    summary = (
        "Investigation completed with limited synthesis. "
        + (f"Observed symptoms: {observed}." if observed else "No dominant symptoms extracted.")
    )
    return SynthesisResult(
        summary=summary,
        findings=[],
        hypotheses=[],
        recommendations=[],
        missing_information=[reason],
    )