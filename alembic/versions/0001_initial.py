"""initial schema: investigations, evidence, documents, document_chunks (pgvector)

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keep in sync with app.config settings.embedding_dim (all-MiniLM-L6-v2 = 384)
EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "investigations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("service", sa.String(255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.String(64),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("raw_payload", JSONB(), nullable=False),
        sa.Column("source_locator", JSONB(), nullable=False),
    )
    op.create_index("ix_evidence_investigation_id", "evidence", ["investigation_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("service", sa.String(255), nullable=True),
        sa.Column("source_uri", sa.String(1024), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(512), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index(
        "ix_document_chunks_embedding",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_content_hash", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_evidence_investigation_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_table("investigations")