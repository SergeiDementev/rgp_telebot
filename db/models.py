"""SQLAlchemy-модели — по backend_plan.md §4, с тремя уточнениями:

- `flee_opportunity_used` разведён на `player_flee_right_used` /
  `enemy_flee_right_used`: право на побег принадлежит стороне, а не сессии
  целиком (см. combat_mechanics.md §6) — общий флаг позволил бы побегу одной
  стороны случайно сжигать право другой.
- `enemy_hp_max` не хранится в сессии — статы моба (включая HP_max)
  статичны и читаются из `content/enemies.json` по `enemy_type`, хранить их
  копию в каждой сессии было бы дублированием статичных данных.
- `Character` никогда не удаляется физически (docs/notes.md, п.41) — "сброс"
  архивирует строку (`is_active=False`), у одного `telegram_user_id` со
  временем накапливается много строк (одна активная, остальные — история
  прошлых прохождений для аналитики). Поэтому `telegram_user_id` больше не
  `UNIQUE` на уровне БД — уникальность "одна активная на пользователя"
  обеспечивается на уровне приложения (тот же принцип, что уже применяется
  к "один активный CombatSession на персонажа").
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from db.session import Base


def _utcnow() -> datetime:
    # Naive UTC, намеренно: колонки — обычный DateTime, без timezone=True
    # (одинаково и на SQLite, и на PostgreSQL, docs/notes.md) — если писать
    # aware, сравнение naive/aware (например, в core.progression.get_current_hp)
    # упадёт после db.refresh().
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True)
    telegram_user_id = Column(Integer, nullable=False, index=True)
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

    # Архивация вместо удаления (docs/notes.md, п.41) — is_active=False
    # помечает законченное прохождение (ручной сброс или победа над боссом),
    # его CombatSession/StatAllocationLog остаются в БД навсегда для
    # аналитики (scripts/export_playtest_stats.py --character-id N).
    is_active = Column(Boolean, nullable=False, default=True)
    archived_at = Column(DateTime, nullable=True)
    archived_reason = Column(String, nullable=True)  # "manual_reset" | "boss_victory"

    # Экономика (docs/notes.md, п.30) — цены/капы в core/economy.py, не здесь.
    gold = Column(Integer, nullable=False, default=0)
    loot = Column(JSON, nullable=False, default=dict)  # {"<item_name>": <count>, ...}
    potions_small = Column(Integer, nullable=False, default=0)
    potions_large = Column(Integer, nullable=False, default=0)

    # Двуязычность (docs/notes.md) — "ru" | "en", по одному на персонажа, не
    # на Telegram-аккаунт: отдельной модели пользователя в проекте нет,
    # персонаж — единственная сущность, за которой закреплён игрок.
    # api/dependencies.py::get_localized_character выставляет по этому полю
    # текущую локаль (core/i18n.py) на время обработки запроса.
    language = Column(String, nullable=False, default="ru")

    # message_id двух постоянных сообщений игрока в Telegram — приветствия и
    # главного игрового экрана (docs/notes.md). Nullable — у персонажа, ещё
    # ни разу не прошедшего /start после раскатки этого поля, их не будет;
    # заполняются впервые при следующем /start (bot/handlers/start.py::
    # cmd_start), который также удаляет и пересоздаёт оба сообщения при
    # повторном вызове вместо накопления истории чата. chat_id отдельно не
    # хранится — бот работает только в приватных чатах, где Telegram
    # гарантирует chat_id == telegram_user_id (тот же принцип, что и во
    # всём остальном API — X-Telegram-User-Id, не chat_id).
    welcome_message_id = Column(Integer, nullable=True)
    main_message_id = Column(Integer, nullable=True)


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

    # Зелья (docs/notes.md, п.31) — лимит "раз за бой", своё поле, не завязан
    # на player_flee_right_used. Только игрок — у моба зелий нет вообще.
    player_potion_used_this_battle = Column(Boolean, nullable=False, default=False)

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
