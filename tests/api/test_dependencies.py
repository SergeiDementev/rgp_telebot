"""Тесты api/dependencies.py::get_localized_character.

Только контракт самой функции ("после await'а — i18n.get_locale() отдаёт
character.language") — то, что async-зависимость FastAPI действительно
пробрасывает contextvars.set() в синхронный эндпоинт (в отличие от
синхронной зависимости — copy_context() в threadpool изолировал бы её),
проверено вручную перед реализацией, отдельным скриптом, не входит в
автоматический прогон."""

from types import SimpleNamespace

import pytest

from api.dependencies import get_localized_character
from core import i18n

pytestmark = pytest.mark.asyncio


async def test_get_localized_character_sets_locale_from_character_language():
    character = SimpleNamespace(language="en")
    try:
        result = await get_localized_character(character)
        assert result is character
        assert i18n.get_locale() == "en"
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)


async def test_get_localized_character_sets_ru_locale():
    character = SimpleNamespace(language="ru")
    try:
        await get_localized_character(character)
        assert i18n.get_locale() == "ru"
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)
