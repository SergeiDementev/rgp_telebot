"""Add welcome_message_id and main_message_id to Character

Revision ID: 71972deef8e3
Revises: faeb907ad3a4
Create Date: 2026-09-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71972deef8e3'
down_revision: Union[str, Sequence[str], None] = 'faeb907ad3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable, без server_default — docs/notes.md: у персонажа, который ещё
    # ни разу не проходил /start после этой миграции, их не будет, заполняются
    # впервые при следующем /start (bot/handlers/start.py::cmd_start).
    op.add_column('characters', sa.Column('welcome_message_id', sa.Integer(), nullable=True))
    op.add_column('characters', sa.Column('main_message_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('characters', 'main_message_id')
    op.drop_column('characters', 'welcome_message_id')
