"""Исключение для ответов по закрытому списку кодов (docs/hardening_plan.md,
этап 4, п.1) — перехватывается обработчиком register_error_handlers() и
превращается в {"error": {"code": ..., "details": {...}}}, вместо
HTTPException с текстом в detail. Этот же файл регистрирует и catch-all
обработчик (этап 6, п.2) — журнал ошибок, не только их форма ответа."""

import traceback as tb_module
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.schemas.errors import ErrorCode, ErrorDetail, ErrorResponse
from db.models import ErrorLog
from db.session import SessionLocal


class GameError(Exception):
    def __init__(self, status_code: int, code: ErrorCode, details: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        super().__init__(f"{code} ({status_code}): {self.details}")


def _log_error(
    session_factory: Callable[[], Session],
    source: str,
    error_type: str,
    message: str,
    context: dict[str, Any],
    traceback: str | None,
) -> None:
    """Собственная сессия, не Depends(get_db) — вызывается из обработчика
    исключений, вне обычного DI-потока запроса (и чужая сессия запроса к
    этому моменту могла быть в испорченном состоянии). Сбой самой записи
    (например, БД недоступна — та же причина, что и у исходной ошибки) не
    должен превратиться во второе необработанное исключение поверх первого."""
    db = session_factory()
    try:
        db.add(ErrorLog(source=source, error_type=error_type, message=message, context=context, traceback=traceback))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def register_error_handlers(app: FastAPI, session_factory: Callable[[], Session] = SessionLocal) -> None:
    """Вызывается и настоящим приложением (api/main.py, с дефолтным
    session_factory=SessionLocal), и тестовыми FastAPI()-приложениями
    роутеров (tests/api/test_*_router.py, с session_factory=db_session_factory
    — своя изолированная БД на тест, не настоящая SessionLocal) — без
    собственного обработчика GameError там улетал бы необработанным (500
    вместо реального статуса), а без правильной session_factory запись в
    error_log из catch-all обработчика ниже шла бы не в ту БД."""

    @app.exception_handler(GameError)
    async def game_error_handler(request: Request, exc: GameError) -> JSONResponse:
        body = ErrorResponse(error=ErrorDetail(code=exc.code, details=exc.details))
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Starlette резолвит обработчик по MRO исключения — GameError здесь
        не теряется, у него уже есть более специфичный обработчик выше."""
        formatted_traceback = "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
        _log_error(
            session_factory,
            source="api",
            error_type=type(exc).__name__,
            message=str(exc),
            context={"path": request.url.path, "method": request.method},
            traceback=formatted_traceback,
        )
        body = ErrorResponse(error=ErrorDetail(code="internal.unexpected_error", details={}))
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=body.model_dump())
