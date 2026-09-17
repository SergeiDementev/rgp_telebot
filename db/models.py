"""SQLAlchemy-модели — по backend_plan.md §4, с двумя уточнениями:

- `flee_opportunity_used` разведён на `player_flee_right_used` /
  `enemy_flee_right_used`: право на побег принадлежит стороне, а не сессии
  целиком (см. combat_mechanics.md §6) — общий флаг позволил бы побегу одной
  стороны случайно сжигать право другой.
- `enemy_hp_max` не хранится в сессии — статы моба (включая HP_max)
  статичны и читаются из `content/enemies.json` по `enemy_type`, хранить их
  копию в каждой сессии было бы дублированием статичных данных.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from db.session import Base


def _utcnow() -> datetime:
    # Naive UTC, намеренно: SQLite не хранит таймзону и при чтении всегда
    # возвращает naive-datetime — если писать aware, сравнение naive/aware
    # (например, в core.progression.get_current_hp) упадёт после db.refresh().
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True)
    telegram_user_id = Column(Integer, unique=True, nullable=False, index=True)
    nickname = Column(String, nullable=False)
    level = Column(Integer, nullable=False, default=1)
    victory_points = Column(Integer, nullable=False, default=0)
    unspent_stat_points = Column(Integer, nullable=False, default=0)
    strength = Column(Integer, nullable=False)
    agility = Column(Integer, nullable=False)
    luck = Column(Integer, nullable=False)
    vitality = Column(Integer, nullable=False)
    hp_current = Column(Float, nullable=False)
    last_hp_update_at = Column(DateTime, nullable=False, default=_utcnow)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class CombatSession(Base):
    __tablename__ = "combat_sessions"

    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False, index=True)

    enemy_type = Column(String, nullable=False)
    enemy_hp_current = Column(Float, nullable=False)
    character_hp_snapshot = Column(Float, nullable=False)

    current_turn = Column(String, nullable=True)  # "player" | "enemy"; None до /start (инициатива ещё не брошена)
    status = Column(String, nullable=False, default="awaiting_initiative")
    # "awaiting_initiative" | "awaiting_confirmation" | "active" | "finished"
    result = Column(String, nullable=True)
    # "victory" | "defeat" | "player_fled" | "enemy_fled"

    circumstance_outcome = Column(String, nullable=True)  # "buff" | "debuff" | None
    circumstance_roller = Column(String, nullable=True)  # "player" | "enemy"
    strength_modifier_player = Column(Float, nullable=False, default=1.0)
    strength_modifier_enemy = Column(Float, nullable=False, default=1.0)

    player_flee_right_used = Column(Boolean, nullable=False, default=False)
    enemy_flee_right_used = Column(Boolean, nullable=False, default=False)

    turn_log = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    character = relationship("Character")


class StatAllocationLog(Base):
    """История выбора статов при прокачке (docs/notes.md) — раньше в БД
    хранился только итоговый результат (текущие значения статов на
    Character), без истории самих решений "на каком уровне что выбрал".
    Пишется при каждом вызове allocate_point, включая распределение
    стартового пула при создании персонажа (тот же эндпоинт/механика)."""

    __tablename__ = "stat_allocation_log"

    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False, index=True)
    stat = Column(String, nullable=False)
    level_at_time = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
