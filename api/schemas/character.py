"""Pydantic-схемы запросов/ответов для роутера character."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

Language = Literal["ru", "en"]
PotionSize = Literal["small", "large"]


class CharacterCreate(BaseModel):
    telegram_user_id: int
    nickname: str = Field(min_length=1, max_length=64)
    # docs/notes.md — дефолт "ru" только ради обратной совместимости тестов,
    # которые создают персонажа без этого поля вообще; бот (реальный
    # единственный клиент) передаёт его всегда явно, определив по
    # message.from_user.language_code при первом /start.
    language: Language = "ru"


class CharacterOut(BaseModel):
    id: int
    telegram_user_id: int
    nickname: str
    level: int
    victory_points: int
    points_to_next_level: int
    unspent_stat_points: int
    strength: int
    agility: int
    luck: int
    vitality: int
    hp_current: float
    hp_max: float
    hp_seconds_to_full: float
    gold: int
    loot: dict[str, int]
    potions_small: int
    potions_large: int
    language: Language
    active_combat_session_id: Optional[int] = None
    welcome_message_id: Optional[int] = None
    main_message_id: Optional[int] = None


class AllocatePointRequest(BaseModel):
    stat: str


class AllocatePointResponse(BaseModel):
    character: CharacterOut


class SellLootResponse(BaseModel):
    character: CharacterOut


class BuyPotionRequest(BaseModel):
    size: PotionSize


class BuyPotionResponse(BaseModel):
    character: CharacterOut


class SetLanguageRequest(BaseModel):
    language: Language


class SetLanguageResponse(BaseModel):
    character: CharacterOut


class SetMessageIdsRequest(BaseModel):
    """Оба поля необязательны и независимы (docs/notes.md) — частичное
    обновление: bot/handlers/start.py::cmd_start шлёт оба разом при (пере)
    создании обеих постоянных сообщений, а bot/handlers/character.py::
    toggle_language обновляет только main_message_id (self-healing на id
    сообщения, на котором физически нажали), не трогая welcome_message_id.
    Не переданное (None) поле — значение персонажа не меняется, не
    сбрасывается в null."""
    welcome_message_id: Optional[int] = None
    main_message_id: Optional[int] = None


class SetMessageIdsResponse(BaseModel):
    character: CharacterOut
