"""Add error_log table

Revision ID: 08d5cc054f81
Revises: b3c2cd383b3e
Create Date: 2026-10-19 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "08d5cc054f81"
down_revision: str | Sequence[str] | None = "b3c2cd383b3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "error_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("error_type", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("traceback", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # docs/hardening_plan.md, этап 4, п.6 — та же дисциплина, что и у
    # остальных CHECK в этом проекте (batch_alter_table — SQLite не умеет
    # ALTER TABLE ADD CONSTRAINT напрямую).
    with op.batch_alter_table("error_log") as batch_op:
        batch_op.create_check_constraint("ck_error_log_source_valid", "source IN ('api', 'bot')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("error_log")
