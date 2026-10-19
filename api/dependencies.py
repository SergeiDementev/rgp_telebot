"""Сквозные FastAPI-зависимости: сессия БД, авторизация бота, текущий персонаж."""

import random

from fastapi import Depends, Header, status
from sqlalchemy.orm import Session

from api.errors import GameError
from api.settings import settings
from core import i18n
from db.models import Character
from db.session import get_db


def require_api_key(x_internal_api_key: str = Header(...)) -> None:
    """§9 backend_plan.md: статический ключ, известный только боту."""
    if x_internal_api_key != settings.internal_api_key:
        raise GameError(status.HTTP_401_UNAUTHORIZED, "auth.invalid_api_key")


def get_rng() -> random.Random:
    """Случайность как зависимость (docs/hardening_plan.md, этап 4, п.4), не
    прямой вызов random.randint в роутерах — тесты задают детерминированную
    последовательность через dependency override (tests/api/conftest.py::
    ScriptedRandom), не через monkeypatch модуля random."""
    return random.Random()


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
        raise GameError(status.HTTP_404_NOT_FOUND, "character.not_found")
    return character


async def get_localized_character(character: Character = Depends(get_current_character)) -> Character:
    """Как get_current_character, плюс выставляет текущую локаль (core/i18n.py)
    из character.language на время обработки запроса — для роутеров, которые
    рендерят игровой текст через api/rendering.py (encounter/combat; сам
    character-роутер текста не рендерит вообще, ему это не нужно).

    Обязательно async def, а не обычная (синхронная) зависимость — FastAPI
    гоняет синхронные зависимости и синхронный эндпоинт через отдельные
    copy_context()-копии в threadpool, поэтому set() внутри синхронной
    зависимости не был бы виден дальше по цепочке; у async-зависимости
    мутация происходит в "живом" контексте event loop, откуда её унаследует
    любая последующая copy_context() для этого же запроса — включая сам
    синхронный эндпоинт. Проверено эмпирически перед реализацией, не только
    по документации."""
    i18n.set_locale(character.language)
    return character
