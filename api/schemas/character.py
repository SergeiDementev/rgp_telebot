"""Pydantic-схемы запросов/ответов для роутера character."""

from pydantic import BaseModel, Field


class CharacterCreate(BaseModel):
    telegram_user_id: int
    nickname: str = Field(min_length=1, max_length=64)


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


class AllocatePointRequest(BaseModel):
    stat: str


class AllocatePointResponse(BaseModel):
    character: CharacterOut


class SellLootResponse(BaseModel):
    character: CharacterOut


class BuyPotionRequest(BaseModel):
    size: str


class BuyPotionResponse(BaseModel):
    character: CharacterOut
