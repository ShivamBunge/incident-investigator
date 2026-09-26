"""API routes: documents, investigations, health."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import Investigation, get_session
from app.models import DocumentCreate, DocumentCreated, InvestigationCreate, InvestigationResult
from app.orchestrator import run_investigation
from app.rag.ingest import ingest_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.post("/documents", response_model=DocumentCreated, status_code=201)
def add_document(payload: DocumentCreate, db: Session = Depends(get_session)) -> DocumentCreated:
    """Add a runbook or postmortem; parses, chunks, embeds, and stores synchronously."""
    document, created = ingest_document(
        db,
        title=payload.title,
        document_type=payload.document_type,
        service=payload.service,
        content=payload.content,
        source_uri=payload.source_uri,
    )
    return DocumentCreated(
        id=document.id,
        title=document.title,
        document_type=document.document_type,
        service=document.service,
        chunk_count=len(document.chunks),
        created=created,
    )


@router.post("/investigations", response_model=InvestigationResult, status_code=201)
async def create_investigation(
    payload: InvestigationCreate, db: Session = Depends(get_session)
) -> InvestigationResult:
    """Run a bounded, evidence-grounded investigation for one service."""
    try:
        return await run_investigation(payload, db)
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the client
        logger.exception("investigation failed")
        raise HTTPException(status_code=500, detail=f"investigation failed: {exc}") from exc


@router.get("/investigations/{investigation_id}", response_model=InvestigationResult)
def get_investigation(investigation_id: str, db: Session = Depends(get_session)):
    """Return a previously stored investigation result."""
    investigation = (
        db.query(Investigation).filter(Investigation.id == investigation_id).first()
    )
    if investigation is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    if investigation.result is None:
        raise HTTPException(status_code=409, detail="investigation has not completed")
    return InvestigationResult.model_validate(investigation.result)