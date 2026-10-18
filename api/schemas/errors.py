"""Закрытый список кодов ошибок API (docs/hardening_plan.md, этап 4, п.1) —
клиент (бот) различает причины отказа по `code`, не разбирая текст на
естественном языке."""

from typing import Any, Literal

from pydantic import BaseModel, Field

ErrorCode = Literal[
    "auth.invalid_api_key",
    "character.not_found",
    "stats.unknown_stat",
    "stats.no_points",
    "economy.cap_reached",
    "economy.not_enough_gold",
    "combat.not_found",
    "combat.not_your_session",
    "combat.unexpected_status",
    "combat.not_your_turn",
    "combat.flee_not_allowed",
    "combat.potion_already_used",
    "combat.potion_not_owned",
    "combat.already_finished",
    "encounter.active_session_exists",
    "encounter.level_too_low",
]


class ErrorDetail(BaseModel):
    code: ErrorCode
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
