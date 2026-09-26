"""add result JSONB column to investigations

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("investigations", sa.Column("result", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("investigations", "result")