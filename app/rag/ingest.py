"""Document ingestion: chunk -> embed -> persist (idempotent by content hash)."""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.db import Document, DocumentChunk, new_id
from app.rag.chunk import chunk_markdown
from app.rag.embed import embed_texts


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def ingest_document(
    db: Session,
    *,
    title: str,
    document_type: str,
    service: str | None,
    content: str,
    source_uri: str | None = None,
) -> tuple[Document, bool]:
    """Parse, chunk, embed, and store a document synchronously.

    Returns (document, created). Re-ingesting identical content is a no-op.
    """
    doc_hash = content_hash(content)
    existing = db.query(Document).filter(Document.content_hash == doc_hash).first()
    if existing is not None:
        return existing, False

    chunks = chunk_markdown(content)
    # Embed heading + body so section context is part of the vector.
    embedded = [f"{c.heading}\n\n{c.content}" if c.heading else c.content for c in chunks]
    vectors = embed_texts(embedded)

    document = Document(
        id=new_id("doc"),
        title=title,
        document_type=document_type,
        service=service,
        source_uri=source_uri,
        content_hash=doc_hash,
    )
    db.add(document)
    db.flush()

    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        db.add(
            DocumentChunk(
                id=new_id("chk"),
                document_id=document.id,
                chunk_index=i,
                heading=chunk.heading,
                content=chunk.content,
                embedding=vector,
                chunk_metadata={
                    "service": service,
                    "document_type": document_type,
                    "title": title,
                },
            )
        )

    db.commit()
    db.refresh(document)
    return document, True