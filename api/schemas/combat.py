"""Pydantic-схемы запросов/ответов для роутеров encounter и combat."""

from typing import Literal, Optional

from pydantic import BaseModel


class EncounterSearchResponse(BaseModel):
    combat_session_id: int
    enemy_type: str
    status: str
    text: str


class CombatStartResponse(BaseModel):
    combat_session_id: int
    status: str
    first_role: str  # "player" | "enemy"
    player_strength_modifier: float
    enemy_strength_modifier: float
    text: str


class ConfirmRequest(BaseModel):
    decision: Literal["fight", "flee"]


class FleeDecisionRequest(BaseModel):
    decision: Literal["flee", "continue"]


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


class CombatSessionOut(BaseModel):
    combat_session_id: int
    enemy_type: str
    status: str
    result: Optional[str] = None
    current_turn: Optional[str] = None
    player_hp_current: float
    enemy_hp_current: float
    enemy_hp_max: float
