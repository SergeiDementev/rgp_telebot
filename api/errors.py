"""Исключение для ответов по закрытому списку кодов (docs/hardening_plan.md,
этап 4, п.1) — перехватывается обработчиком register_error_handlers() и
превращается в {"error": {"code": ..., "details": {...}}}, вместо
HTTPException с текстом в detail."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.schemas.errors import ErrorCode, ErrorDetail, ErrorResponse


class GameError(Exception):
    def __init__(self, status_code: int, code: ErrorCode, details: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        super().__init__(f"{code} ({status_code}): {self.details}")


def register_error_handlers(app: FastAPI) -> None:
    """Вызывается и настоящим приложением (api/main.py), и тестовыми
    FastAPI()-приложениями роутеров (tests/api/test_*_router.py) — иначе
    GameError там улетал бы необработанным (500 вместо реального статуса)."""

    @app.exception_handler(GameError)
    async def game_error_handler(request: Request, exc: GameError) -> JSONResponse:
        body = ErrorResponse(error=ErrorDetail(code=exc.code, details=exc.details))
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())
