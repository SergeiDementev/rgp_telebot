"""Split message ids into character_message_state table

Revision ID: 3dd9a68a8884
Revises: 71972deef8e3
Create Date: 2026-10-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3dd9a68a8884"
down_revision: str | Sequence[str] | None = "71972deef8e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # docs/hardening_plan.md, этап 4, п.7 — состояние интерфейса бота
    # (message_id), не игровые данные персонажа, в отдельной таблице.
    # character_id — и PK, и FK: максимум одна строка на персонажа без
    # отдельного уникального индекса.
    op.create_table(
        "character_message_state",
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("welcome_message_id", sa.Integer(), nullable=True),
        sa.Column("main_message_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.PrimaryKeyConstraint("character_id"),
    )

    # Перенос существующих данных — только там, где хоть одно поле заполнено,
    # не плодить пустые строки для персонажей, ещё не проходивших /start.
    op.execute(
        """
        INSERT INTO character_message_state (character_id, welcome_message_id, main_message_id)
        SELECT id, welcome_message_id, main_message_id
        FROM characters
        WHERE welcome_message_id IS NOT NULL OR main_message_id IS NOT NULL
        """
    )

    op.drop_column("characters", "main_message_id")
    op.drop_column("characters", "welcome_message_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("characters", sa.Column("welcome_message_id", sa.Integer(), nullable=True))
    op.add_column("characters", sa.Column("main_message_id", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE characters
        SET welcome_message_id = character_message_state.welcome_message_id,
            main_message_id = character_message_state.main_message_id
        FROM character_message_state
        WHERE characters.id = character_message_state.character_id
        """
    )

    op.drop_table("character_message_state")
