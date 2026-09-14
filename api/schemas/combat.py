"""Pydantic-схемы запросов/ответов для роутеров encounter и combat.

Пополняется по мере реализации шагов боя — сейчас только поиск противника
и запуск инициативы/обстоятельства (см. api/routers/encounter.py).
"""

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
