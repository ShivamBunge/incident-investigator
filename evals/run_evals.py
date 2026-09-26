"""Evaluation harness (spec Section 11).

Modes:
    python -m evals.run_evals --retrieval      Recall@1/3/5 over seeded scenarios
    python -m evals.run_evals --investigation  root-cause accuracy, tool selection,
                                               evidence coverage, unsupported-claim
                                               rate, latency (requires OPENROUTER_API_KEY)
    python -m evals.run_evals --all            both

Exit codes: 0 = pass, 1 = threshold failure, 2 = setup problem.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

DATASET_PATH = Path(__file__).parent / "dataset.json"

# Keywords too generic to count toward root-cause matching.
_CAUSE_STOPWORDS = {"database", "recent", "failure", "error"}


def _stem(word: str) -> str:
    """Light suffix stripping so 'exhaustion' matches 'exhausted', etc."""
    for suffix in ("ions", "ion", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 5:
            return word[: len(word) - len(suffix)]
    return word


# Semantic equivalents accepted when matching the expected root cause, e.g.
# "the release of v1.5.0 introduced a bug" identifies a deployment regression.
_CAUSE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "deployment": ("deployment", "deploy", "deployed", "release", "rollout"),
    "regression": ("regression", "regressed", "bug", "introduced"),
    "exhaustion": ("exhaust", "exhausted", "exhaustion"),
    "dependency": ("dependency", "downstream", "upstream"),
}


def _keyword_hit(keyword: str, lowered_statement: str) -> bool:
    variants = _CAUSE_SYNONYMS.get(keyword, (keyword,))
    return any(_stem(v) in lowered_statement for v in variants)


# --- Retrieval evaluation -----------------------------------------------------


def evaluate_retrieval(cases: list[dict]) -> dict:
    from app.db import Document, SessionLocal
    from app.rag.retrieve import retrieve_chunks

    db = SessionLocal()
    try:
        indexed = db.query(Document).count()
        if indexed == 0:
            print("No documents indexed. Run: python scripts/seed_docs.py")
            sys.exit(2)

        results = []
        for case in cases:
            chunks = retrieve_chunks(db, case["rag_query"], k=5, service=case.get("service"))
            titles = [c.document_title for c in chunks]
            expected = case["expected_document_title"]
            results.append(
                {
                    "id": case["id"],
                    "expected": expected,
                    "retrieved_titles": titles,
                    "recall@1": expected in titles[:1],
                    "recall@3": expected in titles[:3],
                    "recall@5": expected in titles[:5],
                }
            )
    finally:
        db.close()

    n = len(results)
    summary = {
        "cases": n,
        "recall@1": sum(r["recall@1"] for r in results) / n if n else 0.0,
        "recall@3": sum(r["recall@3"] for r in results) / n if n else 0.0,
        "recall@5": sum(r["recall@5"] for r in results) / n if n else 0.0,
    }
    return {"summary": summary, "results": results}


def print_retrieval_report(report: dict) -> None:
    print("=" * 64)
    print("RETRIEVAL EVALUATION")
    print("=" * 64)
    for r in report["results"]:
        status = "PASS" if r["recall@3"] else "FAIL"
        print(f"\n[{status}] {r['id']}")
        print(f"  expected: {r['expected']}")
        for i, title in enumerate(r["retrieved_titles"], 1):
            marker = "->" if title == r["expected"] else "  "
            print(f"  {marker} {i}. {title}")
    print("=" * 64)
    s = report["summary"]
    print(f"Recall@1: {s['recall@1']:.2f}   Recall@3: {s['recall@3']:.2f}   Recall@5: {s['recall@5']:.2f}")


# --- Investigation evaluation ---------------------------------------------------


def _cause_keywords(expected_cause: str) -> list[str]:
    words = re.findall(r"[a-z]+", expected_cause.lower())
    return [w for w in words if w not in _CAUSE_STOPWORDS] or words


def _hypothesis_matches(statement: str, keywords: list[str], threshold: float = 0.7) -> bool:
    lowered = statement.lower()
    hits = sum(1 for k in keywords if _keyword_hit(k, lowered))
    return (hits / len(keywords)) >= threshold if keywords else False


async def evaluate_investigation(cases: list[dict]) -> dict:
    from app.db import SessionLocal
    from app.models import InvestigationCreate, TimeRange
    from app.orchestrator import run_investigation

    results = []
    db = SessionLocal()
    try:
        for case in cases:
            payload = InvestigationCreate(
                question=case["question"],
                service=case["service"],
                time_range=TimeRange(**case["time_range"]),
            )
            started = time.perf_counter()
            result = await run_investigation(payload, db)
            latency = time.perf_counter() - started

            keywords = _cause_keywords(case["expected_root_cause"])

            # A hypothesis counts as identifying the cause when it either states
            # the expected cause (stem-matched) or is grounded in the expected
            # runbook/postmortem chunk.
            rag_summaries = {
                ev.id: ev.summary.lower()
                for ev in result.evidence
                if ev.evidence_type in ("runbook_chunk", "postmortem_chunk")
            }

            def _matches(hypothesis) -> bool:
                if _hypothesis_matches(hypothesis.statement, keywords):
                    return True
                return any(
                    case["expected_document_title"].lower() in rag_summaries.get(eid, "")
                    for eid in hypothesis.supporting_evidence_ids
                )

            hypotheses = result.hypotheses
            top1 = bool(hypotheses) and _matches(hypotheses[0])
            top3 = any(_matches(h) for h in hypotheses[:3])

            tools_used = {
                ev.source_locator.get("tool")
                for ev in result.evidence
                if ev.source_locator.get("tool")
            }
            expected_tools = set(case.get("expected_tools", []))
            tool_rate = (
                len(expected_tools & tools_used) / len(expected_tools) if expected_tools else 1.0
            )

            evidence_types = {ev.evidence_type for ev in result.evidence}
            expected_types = set(case.get("expected_evidence_types", []))
            coverage = (
                len(expected_types & evidence_types) / len(expected_types)
                if expected_types
                else 1.0
            )

            claims = len(result.findings) + len(result.hypotheses)
            unsupported_rate = (
                len(result.rejected_evidence_ids) / claims if claims else 0.0
            )

            rag_titles = sorted(
                {
                    m.group(1)
                    for ev in result.evidence
                    if ev.evidence_type in ("runbook_chunk", "postmortem_chunk")
                    for m in [re.search(r'"([^"]+)"', ev.summary)]
                    if m
                }
            )
            results.append(
                {
                    "id": case["id"],
                    "latency_seconds": round(latency, 2),
                    "evidence_count": len(result.evidence),
                    "rag_titles": rag_titles,
                    "hypotheses": [
                        {
                            "statement": h.statement,
                            "confidence": h.confidence,
                            "supporting": h.supporting_evidence_ids,
                        }
                        for h in hypotheses
                    ],
                    "root_cause_top1": top1,
                    "root_cause_top3": top3,
                    "tool_selection_rate": round(tool_rate, 3),
                    "evidence_coverage": round(coverage, 3),
                    "unsupported_claim_rate": round(unsupported_rate, 3),
                    "unavailable_sources": result.unavailable_sources,
                    "missing_information": result.missing_information,
                }
            )
    finally:
        db.close()

    n = len(results)
    summary = {
        "cases": n,
        "root_cause_top1_accuracy": sum(r["root_cause_top1"] for r in results) / n if n else 0.0,
        "root_cause_top3_accuracy": sum(r["root_cause_top3"] for r in results) / n if n else 0.0,
        "avg_tool_selection_rate": (
            sum(r["tool_selection_rate"] for r in results) / n if n else 0.0
        ),
        "avg_evidence_coverage": sum(r["evidence_coverage"] for r in results) / n if n else 0.0,
        "avg_unsupported_claim_rate": (
            sum(r["unsupported_claim_rate"] for r in results) / n if n else 0.0
        ),
        "avg_latency_seconds": (
            sum(r["latency_seconds"] for r in results) / n if n else 0.0
        ),
    }
    return {"summary": summary, "results": results}


def print_investigation_report(report: dict) -> None:
    print("=" * 64)
    print("INVESTIGATION EVALUATION")
    print("=" * 64)
    for r in report["results"]:
        print(f"\n{r['id']}  (latency {r['latency_seconds']}s, evidence {r['evidence_count']})")
        print(f"  root-cause top-1: {'PASS' if r['root_cause_top1'] else 'FAIL'}   top-3: {'PASS' if r['root_cause_top3'] else 'FAIL'}")
        print(f"  tool selection: {r['tool_selection_rate']:.2f}   evidence coverage: {r['evidence_coverage']:.2f}   unsupported claims: {r['unsupported_claim_rate']:.2f}")
        if r["unavailable_sources"]:
            print(f"  unavailable: {', '.join(r['unavailable_sources'])}")
        print(f"  rag docs retrieved: {r['rag_titles']}")
        for i, h in enumerate(r["hypotheses"][:3], 1):
            print(f"  hyp {i} (conf {h['confidence']}): {h['statement'][:100]}")
            print(f"          supporting: {h['supporting']}")
        if r["missing_information"]:
            print(f"  missing: {r['missing_information'][:2]}")
    print("=" * 64)
    s = report["summary"]
    print(f"root-cause top-1: {s['root_cause_top1_accuracy']:.2f}   top-3: {s['root_cause_top3_accuracy']:.2f}")
    print(f"tool selection: {s['avg_tool_selection_rate']:.2f}   evidence coverage: {s['avg_evidence_coverage']:.2f}")
    print(f"unsupported-claim rate: {s['avg_unsupported_claim_rate']:.2f}   avg latency: {s['avg_latency_seconds']:.1f}s")


# --- Entry point -----------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Incident investigator evaluation harness")
    parser.add_argument("--retrieval", action="store_true", help="Run retrieval evaluation")
    parser.add_argument("--investigation", action="store_true", help="Run investigation evaluation")
    parser.add_argument("--all", action="store_true", help="Run both")
    parser.add_argument("--dataset", default=str(DATASET_PATH), help="Path to dataset.json")
    args = parser.parse_args()

    if not (args.retrieval or args.investigation or args.all):
        parser.print_help()
        return

    with open(args.dataset, encoding="utf-8") as f:
        dataset = json.load(f)

    exit_code = 0

    if args.retrieval or args.all:
        report = evaluate_retrieval(dataset["retrieval_cases"])
        print_retrieval_report(report)
        # Exit condition (Phase 1): correct document in top-3 for every scenario.
        if report["summary"]["recall@3"] < 1.0:
            exit_code = 1

    if args.investigation or args.all:
        import asyncio

        report = asyncio.run(evaluate_investigation(dataset["retrieval_cases"]))
        print_investigation_report(report)
        # Exit condition (Phase 4/5): evidence-backed root cause in top-3 for all.
        if report["summary"]["root_cause_top3_accuracy"] < 1.0:
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()