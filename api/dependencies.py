"""Сквозные FastAPI-зависимости: сессия БД, авторизация бота, текущий персонаж."""

import os

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from db.models import Character
from db.session import get_db

INTERNAL_API_KEY_ENV = "INTERNAL_API_KEY"
DEV_DEFAULT_API_KEY = "dev-local-key"  # только для локальной разработки без .env


def require_api_key(x_internal_api_key: str = Header(...)) -> None:
    """§9 backend_plan.md: статический ключ, известный только боту."""
    expected = os.environ.get(INTERNAL_API_KEY_ENV, DEV_DEFAULT_API_KEY)
    if x_internal_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")


def get_current_character(
    x_telegram_user_id: int = Header(...),
    db: Session = Depends(get_db),
) -> Character:
    """Персонаж текущего запроса — по telegram_user_id из заголовка, не из тела
    запроса: бот сам знает, кто ему пишет, клиент не может подменить чужого
    персонажа, просто передав другой id в JSON.

    Фильтр по is_active обязателен (docs/notes.md, п.41) — telegram_user_id
    больше не уникален в БД: у пользователя может быть накоплено сколько
    угодно архивных персонажей (прошлые прохождения), нужен именно текущий."""
    character = (
        db.query(Character)
        .filter(Character.telegram_user_id == x_telegram_user_id, Character.is_active.is_(True))
        .first()
    )
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="character not found")
    return character
