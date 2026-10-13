"""Add language to Character

Revision ID: faeb907ad3a4
Revises: 2cb51eceab60
Create Date: 2026-09-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "faeb907ad3a4"
down_revision: str | Sequence[str] | None = "2cb51eceab60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default нужен вручную (см. ea824ed5db49) — таблица не пустая.
    op.add_column("characters", sa.Column("language", sa.String(), nullable=False, server_default="ru"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("characters", "language")
