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
    # Необработанное исключение (docs/hardening_plan.md, этап 6, п.2) — не
    # GameError, перехвачено catch-all обработчиком в api/errors.py и
    # залогировано в error_log; этот код — единственный способ отличить
    # "мы предвидели этот отказ" от "в коде баг", не разбирая message.
    "internal.unexpected_error",
]


class ErrorDetail(BaseModel):
    code: ErrorCode
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ErrorReportRequest(BaseModel):
    """Бот репортит сюда свои необработанные исключения (docs/hardening_plan.md,
    этап 6, п.2) — `source` не поле запроса: эндпоинт всегда пишет "bot",
    сервер не доверяет клиенту указывать, откуда пришла ошибка."""

    error_type: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    traceback: str | None = None
