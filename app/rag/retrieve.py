"""Vector retrieval over pgvector with metadata filters.

Pipeline (spec Section 5.4):
question + observed error signatures -> embedding -> vector similarity
-> service/document-type filter -> top-k chunks -> citations
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db import Document, DocumentChunk
from app.rag.embed import embed_query


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_title: str
    document_type: str
    service: str | None
    heading: str | None
    content: str
    score: float  # cosine similarity, higher is better


def retrieve_chunks(
    db: Session,
    query: str,
    *,
    k: int = 5,
    service: str | None = None,
    document_type: str | None = None,
) -> list[RetrievedChunk]:
    """Top-k chunks by cosine similarity with optional metadata filters."""
    query_vector = embed_query(query)
    distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")

    stmt: Select = (
        select(DocumentChunk, Document, distance)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.embedding.isnot(None))
        .order_by(distance.asc())
        .limit(k)
    )
    if service is not None:
        stmt = stmt.where(Document.service == service)
    if document_type is not None:
        stmt = stmt.where(Document.document_type == document_type)

    rows = db.execute(stmt).all()

    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=document.id,
            document_title=document.title,
            document_type=document.document_type,
            service=document.service,
            heading=chunk.heading,
            content=chunk.content,
            score=round(1.0 - float(distance), 4),
        )
        for chunk, document, distance in rows
    ]