"""Add CHECK constraints and one-active-character-per-player unique index

Revision ID: b3c2cd383b3e
Revises: 3dd9a68a8884
Create Date: 2026-10-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c2cd383b3e"
down_revision: str | Sequence[str] | None = "3dd9a68a8884"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# docs/hardening_plan.md, этап 4, п.6 — границы там, где значение не может
# выйти за них (уровни/очки/здоровье), и закрытые перечисления (язык,
# статус боя и т.п.), которые раньше были только в комментариях/Pydantic.
#
# Осознанно НЕ добавлено: верхняя граница hp_current/enemy_hp_current по
# формуле hp_max (core/progression.py) и ограничение strength_modifier_* —
# обе зависят от калибровочных констант, а не от инварианта; привязывать
# схему БД к ним означало бы третье место дублирования формулы (план сам
# просит устранить дублирование формул отдельно, п.5, не плодить новое).
# Аналогично enemy_type не ограничен списком — это игровой контент
# (content/enemies.json), а не инвариант данных.
CHARACTERS_CHECKS = [
    ("ck_characters_level_positive", "level >= 1"),
    ("ck_characters_victory_points_non_negative", "victory_points >= 0"),
    ("ck_characters_unspent_stat_points_non_negative", "unspent_stat_points >= 0"),
    ("ck_characters_strength_non_negative", "strength >= 0"),
    ("ck_characters_agility_non_negative", "agility >= 0"),
    ("ck_characters_luck_non_negative", "luck >= 0"),
    ("ck_characters_vitality_non_negative", "vitality >= 0"),
    ("ck_characters_hp_current_non_negative", "hp_current >= 0"),
    ("ck_characters_gold_non_negative", "gold >= 0"),
    ("ck_characters_potions_small_non_negative", "potions_small >= 0"),
    ("ck_characters_potions_large_non_negative", "potions_large >= 0"),
    ("ck_characters_language_valid", "language IN ('ru', 'en')"),
    (
        "ck_characters_archived_reason_valid",
        "archived_reason IN ('manual_reset', 'boss_victory') OR archived_reason IS NULL",
    ),
]

COMBAT_SESSIONS_CHECKS = [
    ("ck_combat_sessions_enemy_hp_current_non_negative", "enemy_hp_current >= 0"),
    ("ck_combat_sessions_character_hp_snapshot_non_negative", "character_hp_snapshot >= 0"),
    ("ck_combat_sessions_current_turn_valid", "current_turn IN ('player', 'enemy') OR current_turn IS NULL"),
    (
        "ck_combat_sessions_status_valid",
        "status IN ('awaiting_initiative', 'awaiting_confirmation', 'active', 'awaiting_flee_decision', 'finished')",
    ),
    (
        "ck_combat_sessions_result_valid",
        "result IN ('victory', 'defeat', 'player_fled', 'enemy_fled') OR result IS NULL",
    ),
    (
        "ck_combat_sessions_circumstance_outcome_valid",
        "circumstance_outcome IN ('buff', 'debuff') OR circumstance_outcome IS NULL",
    ),
    (
        "ck_combat_sessions_circumstance_roller_valid",
        "circumstance_roller IN ('player', 'enemy') OR circumstance_roller IS NULL",
    ),
]

STAT_ALLOCATION_LOG_CHECKS = [
    ("ck_stat_allocation_log_stat_valid", "stat IN ('strength', 'agility', 'luck', 'vitality')"),
    ("ck_stat_allocation_log_level_at_time_positive", "level_at_time >= 1"),
]

ACTIVE_CHARACTER_INDEX = "ix_characters_telegram_user_id_active_unique"


def upgrade() -> None:
    """Upgrade schema."""
    # batch_alter_table — SQLite не умеет ALTER TABLE ADD CONSTRAINT напрямую,
    # Alembic в batch-режиме пересобирает таблицу под капотом; на PostgreSQL
    # это прозрачно превращается в обычный ALTER TABLE.
    dialect = op.get_bind().dialect.name

    with op.batch_alter_table("characters") as batch_op:
        for name, condition in CHARACTERS_CHECKS:
            batch_op.create_check_constraint(name, condition)
        # Один активный персонаж на telegram_user_id (docs/notes.md,
        # db/models.py::Character) — раньше гарантировалось только на уровне
        # приложения (api/routers/character.py::create_character), это
        # страховка от гонки/будущего бага, не замена существующей проверки.
        # sqlite_where здесь обязателен ИМЕННО внутри batch_op — обычный
        # op.create_index с ним снаружи batch-блока на SQLite не сработал бы
        # так же надёжно при пересборке таблицы. На PostgreSQL batch-режим
        # создал бы индекс БЕЗ WHERE (sqlite_where игнорируется другим
        # диалектом) — ошибочно сделав telegram_user_id уникальным вообще
        # (сломало бы архивацию персонажей), поэтому здесь только для SQLite.
        if dialect == "sqlite":
            batch_op.create_index(
                ACTIVE_CHARACTER_INDEX, ["telegram_user_id"], unique=True, sqlite_where=sa.text("is_active")
            )

    with op.batch_alter_table("combat_sessions") as batch_op:
        for name, condition in COMBAT_SESSIONS_CHECKS:
            batch_op.create_check_constraint(name, condition)

    with op.batch_alter_table("stat_allocation_log") as batch_op:
        for name, condition in STAT_ALLOCATION_LOG_CHECKS:
            batch_op.create_check_constraint(name, condition)

    if dialect == "postgresql":
        op.execute(f'CREATE UNIQUE INDEX "{ACTIVE_CHARACTER_INDEX}" ON characters (telegram_user_id) WHERE is_active')


def downgrade() -> None:
    """Downgrade schema."""
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        op.execute(f'DROP INDEX IF EXISTS "{ACTIVE_CHARACTER_INDEX}"')

    with op.batch_alter_table("stat_allocation_log") as batch_op:
        for name, _condition in STAT_ALLOCATION_LOG_CHECKS:
            batch_op.drop_constraint(name, type_="check")

    with op.batch_alter_table("combat_sessions") as batch_op:
        for name, _condition in COMBAT_SESSIONS_CHECKS:
            batch_op.drop_constraint(name, type_="check")

    with op.batch_alter_table("characters") as batch_op:
        if dialect == "sqlite":
            batch_op.drop_index(ACTIVE_CHARACTER_INDEX)
        for name, _condition in CHARACTERS_CHECKS:
            batch_op.drop_constraint(name, type_="check")
