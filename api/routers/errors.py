"""Роутер /errors — бот репортит сюда свои необработанные исключения
(docs/hardening_plan.md, этап 6, п.2), чтобы ошибки API и бота были видны
в одном месте (db.models.ErrorLog). Собственные ошибки API пишутся туда же
catch-all обработчиком в api/errors.py, не через этот эндпоинт."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from api.dependencies import get_db, require_api_key
from api.schemas.errors import ErrorReportRequest
from db.models import ErrorLog

router = APIRouter(prefix="/errors", tags=["errors"], dependencies=[Depends(require_api_key)])


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def report_error(payload: ErrorReportRequest, db: Session = Depends(get_db)) -> None:
    # source всегда "bot" здесь, не из payload — единственный вызывающий
    # этот эндпоинт клиент — бот, и мы не доверяем клиенту указывать,
    # откуда пришла ошибка (тот же принцип, что и везде в api/).
    db.add(
        ErrorLog(
            source="bot",
            error_type=payload.error_type,
            message=payload.message,
            context=payload.context,
            traceback=payload.traceback,
        )
    )
    db.commit()
