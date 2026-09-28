"""Pydantic-схемы запросов/ответов для роутеров encounter и combat."""

from typing import Literal, Optional

from pydantic import BaseModel


class EncounterSearchResponse(BaseModel):
    combat_session_id: int
    enemy_type: str
    status: str
    text: str
    potions_small: int
    potions_large: int
    # docs/notes.md — character.language, уже в scope у эндпоинта (get_
    # localized_character) без лишнего запроса: бот использует его, чтобы
    # выставить локаль перед построением клавиатуры в хендлерах, которые
    # сами персонажа не запрашивают (иначе клавиатура ориентировалась бы на
    # язык клиента Telegram, а не на явно выбранный язык персонажа).
    language: str


class CombatStartResponse(BaseModel):
    combat_session_id: int
    status: str
    first_role: str  # "player" | "enemy"
    enemy_type: str
    player_strength_modifier: float
    enemy_strength_modifier: float
    text: str
    language: str


class ConfirmRequest(BaseModel):
    decision: Literal["fight", "flee"]


class FleeDecisionRequest(BaseModel):
    decision: Literal["flee", "continue"]


class TurnRequest(BaseModel):
    power_attack: bool = False


class UsePotionRequest(BaseModel):
    size: Literal["small", "large"]


class CombatTurnResponse(BaseModel):
    combat_session_id: int
    status: str
    result: Optional[str] = None
    current_turn: Optional[str] = None
    enemy_type: str
    text: str
    potions_small: int
    potions_large: int
    potion_used_this_battle: bool
    language: str


class CombatSessionOut(BaseModel):
    combat_session_id: int
    enemy_type: str
    status: str
    result: Optional[str] = None
    current_turn: Optional[str] = None
    player_hp_current: float
    enemy_hp_current: float
    enemy_hp_max: float
    language: str
