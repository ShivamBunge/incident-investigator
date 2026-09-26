"""Smoke test for Phase 1b: chunk -> embed -> ingest -> count.

Run from the project root with the venv active:
    python scripts/smoke_rag.py
"""

from app.db import SessionLocal
from app.rag.chunk import chunk_markdown, estimate_tokens
from app.rag.ingest import ingest_document

DOC_PATH = "docs/runbooks/db_pool_exhaustion.md"


def main() -> None:
    with open(DOC_PATH, encoding="utf-8") as f:
        md = f.read()

    chunks = chunk_markdown(md)
    print(f"chunks: {len(chunks)}")
    for c in chunks:
        print(f"  - heading={c.heading!r} tokens~{estimate_tokens(c.content)}")

    db = SessionLocal()
    try:
        doc, created = ingest_document(
            db,
            title="Checkout DB Connection Pool Exhaustion Runbook",
            document_type="runbook",
            service="checkout-api",
            content=md,
        )
        print(f"document: {doc.id} created={created}")
        print(f"stored chunks: {len(doc.chunks)}")

        # Idempotency check: re-ingesting identical content must not duplicate.
        doc2, created2 = ingest_document(
            db,
            title="Checkout DB Connection Pool Exhaustion Runbook",
            document_type="runbook",
            service="checkout-api",
            content=md,
        )
        print(f"re-ingest: id={doc2.id} created={created2} (expect same id, created=False)")
    finally:
        db.close()


if __name__ == "__main__":
    main()