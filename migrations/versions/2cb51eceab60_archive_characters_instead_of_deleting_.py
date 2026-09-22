"""Archive characters instead of deleting them

Revision ID: 2cb51eceab60
Revises: 0d0d2f5c17db
Create Date: 2026-09-18 12:54:21.620385

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2cb51eceab60'
down_revision: Union[str, Sequence[str], None] = '0d0d2f5c17db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default нужен вручную (см. ea824ed5db49) — таблица не пустая.
    op.add_column('characters', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('characters', sa.Column('archived_at', sa.DateTime(), nullable=True))
    op.add_column('characters', sa.Column('archived_reason', sa.String(), nullable=True))

    # docs/notes.md, п.41: сброс персонажа больше не удаляет строку, а
    # архивирует (is_active=False) — со временем у одного telegram_user_id
    # накопится много строк (история прошлых прохождений), UNIQUE-индекс на
    # это поле сломал бы создание нового персонажа после архивации старого.
    op.drop_index('ix_characters_telegram_user_id', table_name='characters')
    op.create_index('ix_characters_telegram_user_id', 'characters', ['telegram_user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_characters_telegram_user_id', table_name='characters')
    op.create_index('ix_characters_telegram_user_id', 'characters', ['telegram_user_id'], unique=True)
    op.drop_column('characters', 'archived_reason')
    op.drop_column('characters', 'archived_at')
    op.drop_column('characters', 'is_active')
