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

Типизированный стиль SQLAlchemy 2.0 (`Mapped[...]`/`mapped_column()`, не
старый `Column(...)`, docs/hardening_plan.md, этап 1) — только ради mypy:
без него атрибуты моделей типизируются как заведомо `Optional`, даже для
колонок с `nullable=False`, и это давало сотни ложных находок во всём
`api/`, которое читает эти атрибуты. Сами колонки в БД не меняются —
`nullable`/типы здесь ровно те же, что были в `Column(...)`, просто
выражены через аннотацию (`Mapped[X]` = NOT NULL, `Mapped[X | None]` =
nullable)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


def _utcnow() -> datetime:
    # Naive UTC, намеренно: колонки — обычный DateTime, без timezone=True
    # (одинаково и на SQLite, и на PostgreSQL, docs/notes.md) — если писать
    # aware, сравнение naive/aware (например, в core.progression.get_current_hp)
    # упадёт после db.refresh().
    return datetime.now(UTC).replace(tzinfo=None)


class CharacterMessageState(Base):
    """message_id двух постоянных сообщений игрока в Telegram — приветствия
    и главного игрового экрана (docs/notes.md). `character_id` — и PK, и FK:
    естественно гарантирует максимум одну строку на персонажа, без
    отдельного уникального индекса. Строки нет, пока персонаж ни разу не
    прошёл /start после раскатки этого поля; создаётся впервые при
    следующем /start (bot/handlers/start.py::cmd_start), который также
    удаляет и пересоздаёт оба сообщения при повторном вызове вместо
    накопления истории чата. chat_id отдельно не хранится — бот работает
    только в приватных чатах, где Telegram гарантирует chat_id ==
    telegram_user_id (тот же принцип, что и во всём остальном API —
    X-Telegram-User-Id, не chat_id)."""

    __tablename__ = "character_message_state"

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), primary_key=True)
    welcome_message_id: Mapped[int | None] = mapped_column(default=None)
    main_message_id: Mapped[int | None] = mapped_column(default=None)

    # Кавычки обязательны (не ложная находка ruff UP037) — Character
    # определён ниже в файле, без них это NameError при импорте модуля.
    character: Mapped["Character"] = relationship(  # noqa: UP037
        "Character", back_populates="message_state"
    )


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(index=True)
    nickname: Mapped[str]
    level: Mapped[int] = mapped_column(default=1)
    victory_points: Mapped[int] = mapped_column(default=0)
    unspent_stat_points: Mapped[int] = mapped_column(default=0)
    strength: Mapped[int]
    agility: Mapped[int]
    luck: Mapped[int]
    vitality: Mapped[int]
    hp_current: Mapped[float]
    last_hp_update_at: Mapped[datetime] = mapped_column(default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    # Архивация вместо удаления (docs/notes.md, п.41) — is_active=False
    # помечает законченное прохождение (ручной сброс или победа над боссом),
    # его CombatSession/StatAllocationLog остаются в БД навсегда для
    # аналитики (scripts/export_playtest_stats.py --character-id N).
    is_active: Mapped[bool] = mapped_column(default=True)
    archived_at: Mapped[datetime | None] = mapped_column(default=None)
    archived_reason: Mapped[str | None] = mapped_column(default=None)  # "manual_reset" | "boss_victory"

    # Экономика (docs/notes.md, п.30) — цены/капы в core/economy.py, не здесь.
    gold: Mapped[int] = mapped_column(default=0)
    loot: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)  # {"<item_name>": <count>, ...}
    potions_small: Mapped[int] = mapped_column(default=0)
    potions_large: Mapped[int] = mapped_column(default=0)

    # Двуязычность (docs/notes.md) — "ru" | "en", по одному на персонажа, не
    # на Telegram-аккаунт: отдельной модели пользователя в проекте нет,
    # персонаж — единственная сущность, за которой закреплён игрок.
    # api/dependencies.py::get_localized_character выставляет по этому полю
    # текущую локаль (core/i18n.py) на время обработки запроса.
    language: Mapped[str] = mapped_column(default="ru")

    # message_id двух постоянных сообщений игрока в Telegram — в отдельной
    # таблице CharacterMessageState (docs/hardening_plan.md, этап 4, п.7):
    # это состояние интерфейса бота, не игровые данные персонажа.
    message_state: Mapped[CharacterMessageState | None] = relationship(
        "CharacterMessageState", back_populates="character", uselist=False
    )


class CombatSession(Base):
    __tablename__ = "combat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)

    enemy_type: Mapped[str]
    enemy_hp_current: Mapped[float]
    character_hp_snapshot: Mapped[float]

    current_turn: Mapped[str | None] = mapped_column(
        default=None
    )  # "player" | "enemy"; None до /start (инициатива ещё не брошена)
    status: Mapped[str] = mapped_column(default="awaiting_initiative")
    # "awaiting_initiative" | "awaiting_confirmation" | "active" | "finished"
    result: Mapped[str | None] = mapped_column(default=None)
    # "victory" | "defeat" | "player_fled" | "enemy_fled"

    circumstance_outcome: Mapped[str | None] = mapped_column(default=None)  # "buff" | "debuff" | None
    circumstance_roller: Mapped[str | None] = mapped_column(default=None)  # "player" | "enemy"
    strength_modifier_player: Mapped[float] = mapped_column(default=1.0)
    strength_modifier_enemy: Mapped[float] = mapped_column(default=1.0)

    player_flee_right_used: Mapped[bool] = mapped_column(default=False)
    enemy_flee_right_used: Mapped[bool] = mapped_column(default=False)

    # Зелья (docs/notes.md, п.31) — лимит "раз за бой", своё поле, не завязан
    # на player_flee_right_used. Только игрок — у моба зелий нет вообще.
    player_potion_used_this_battle: Mapped[bool] = mapped_column(default=False)

    turn_log: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    character: Mapped[Character] = relationship("Character")


class StatAllocationLog(Base):
    """История выбора статов при прокачке (docs/notes.md) — раньше в БД
    хранился только итоговый результат (текущие значения статов на
    Character), без истории самих решений "на каком уровне что выбрал".
    Пишется при каждом вызове allocate_point, включая распределение
    стартового пула при создании персонажа (тот же эндпоинт/механика)."""

    __tablename__ = "stat_allocation_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)
    stat: Mapped[str]
    level_at_time: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class ErrorLog(Base):
    """Журнал ошибок API и бота в одном месте (docs/hardening_plan.md, этап
    6, п.2) — независимая находка, не пересекается с CombatSession.turn_log
    (тот про игровые события, этот про необработанные исключения). Без FK
    на Character — ошибка может случиться и без известного персонажа
    (например, 401 до того, как кто-либо распознан); контекст свободной
    формы (JSON), не жёсткая схема на каждый возможный случай."""

    __tablename__ = "error_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str]  # "api" | "bot"
    error_type: Mapped[str]
    message: Mapped[str]
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    traceback: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
