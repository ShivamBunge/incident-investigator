"""Seed the RAG index from docs/ (runbooks + postmortems).

Run from the project root with the venv active:
    python scripts/seed_docs.py
"""

from pathlib import Path

from app.db import SessionLocal
from app.rag.ingest import ingest_document

DOCS_DIR = Path("docs")

# (relative path, title, document_type, service)
SEED: list[tuple[str, str, str, str]] = [
    (
        "runbooks/db_pool_exhaustion.md",
        "Checkout DB Connection Pool Exhaustion Runbook",
        "runbook",
        "checkout-api",
    ),
    (
        "runbooks/downstream_dependency_timeout.md",
        "Downstream Dependency Timeout Runbook",
        "runbook",
        "checkout-api",
    ),
    (
        "runbooks/deployment_regression.md",
        "Deployment Regression Runbook",
        "runbook",
        "checkout-api",
    ),
    (
        "runbooks/traffic_spike_capacity.md",
        "Traffic Spike and Capacity Runbook",
        "runbook",
        "checkout-api",
    ),
    (
        "postmortems/db_pool_exhaustion_postmortem.md",
        "Postmortem: Checkout Outage from Database Connection Pool Exhaustion",
        "postmortem",
        "checkout-api",
    ),
]


def main() -> None:
    db = SessionLocal()
    try:
        for rel, title, doc_type, service in SEED:
            path = DOCS_DIR / rel
            content = path.read_text(encoding="utf-8")
            doc, created = ingest_document(
                db,
                title=title,
                document_type=doc_type,
                service=service,
                content=content,
                source_uri=str(path),
            )
            print(f"{rel}: id={doc.id} created={created} chunks={len(doc.chunks)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()