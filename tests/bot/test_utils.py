"""Тесты bot/utils.py — safe_edit_text, detect_language, get_character_or_prompt_start."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.client import ApiError
from bot.utils import (
    detect_language,
    get_character_or_prompt_start,
    safe_edit_text,
    set_locale_from_telegram_profile,
    start_game_keyboard,
    welcome_text,
)
from core import i18n


def make_message() -> MagicMock:
    message = MagicMock()
    message.edit_text = AsyncMock()
    return message


def make_callback(user_id: int = 1) -> MagicMock:
    callback = MagicMock()
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_safe_edit_text_calls_edit_text_normally():
    message = make_message()

    await safe_edit_text(message, "hello", reply_markup="markup")

    message.edit_text.assert_awaited_once_with("hello", reply_markup="markup")


@pytest.mark.asyncio
async def test_safe_edit_text_swallows_not_modified_error():
    # Кнопка "Обновить" при отсутствии изменений (например, HP уже полное) —
    # Telegram отвечает "message is not modified", раньше это исключение
    # прерывало хендлер до callback.answer() и кнопка выглядела зависшей.
    message = make_message()
    message.edit_text.side_effect = TelegramBadRequest(
        method=MagicMock(), message="Bad Request: message is not modified: ..."
    )

    await safe_edit_text(message, "same text")  # не должно бросить исключение


@pytest.mark.asyncio
async def test_safe_edit_text_reraises_other_bad_request_errors():
    message = make_message()
    message.edit_text.side_effect = TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found")

    with pytest.raises(TelegramBadRequest):
        await safe_edit_text(message, "text")


@pytest.mark.parametrize("language_code", ["ru", "ru-RU", "ru-KZ"])
def test_detect_language_recognizes_russian_variants(language_code):
    assert detect_language(language_code) == "ru"


@pytest.mark.parametrize("language_code", ["en", "en-US", "de", "fr-FR", "uk"])
def test_detect_language_defaults_to_english_for_other_codes(language_code):
    assert detect_language(language_code) == "en"


def test_detect_language_defaults_to_english_when_missing():
    # docs/notes.md — Telegram не гарантирует language_code вообще.
    assert detect_language(None) == "en"


@pytest.mark.asyncio
async def test_get_character_or_prompt_start_sets_locale_from_character_language():
    # docs/notes.md, блок 3 — единственная общая точка входа для character.py/
    # combat.py/language.py, поэтому именно здесь выставляется core.i18n
    # локаль на время обработки колбэка.
    callback = make_callback()
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "language": "en"}
    try:
        character = await get_character_or_prompt_start(callback, api)
        assert character == {"id": 1, "language": "en"}
        assert i18n.get_locale() == "en"
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)


@pytest.mark.asyncio
async def test_get_character_or_prompt_start_defaults_locale_when_language_missing():
    # Реальный API всегда отдаёт language (обязательное поле), но защитный
    # .get(..., DEFAULT_LOCALE) не должен падать на моках без него.
    callback = make_callback()
    api = AsyncMock()
    api.get_character.return_value = {"id": 1}
    try:
        await get_character_or_prompt_start(callback, api)
        assert i18n.get_locale() == i18n.DEFAULT_LOCALE
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)


@pytest.mark.asyncio
async def test_get_character_or_prompt_start_returns_none_and_prompts_on_404():
    callback = make_callback()
    api = AsyncMock()
    api.get_character.side_effect = ApiError(404, "not found")

    character = await get_character_or_prompt_start(callback, api)

    assert character is None
    callback.message.edit_text.assert_awaited_once()
    callback.answer.assert_awaited_once()


def test_welcome_text_switches_with_locale():
    # docs/notes.md, блок 4 — функция, не константа, значение зависит от
    # core.i18n.get_locale().
    token = i18n.set_locale("en")
    try:
        assert welcome_text() == i18n.t("start.welcome")
        assert "Welcome to the text RPG" in welcome_text()
    finally:
        i18n.reset_locale(token)
    assert "Добро пожаловать" in welcome_text()


def test_start_game_keyboard_label_switches_with_locale():
    token = i18n.set_locale("en")
    try:
        markup = start_game_keyboard()
        assert markup.inline_keyboard[0][0].text == "✅ Start the game"
    finally:
        i18n.reset_locale(token)


@pytest.mark.asyncio
async def test_set_locale_from_telegram_profile_sets_ru_and_calls_handler():
    callback = make_callback()
    callback.from_user.language_code = "ru-RU"
    handler = AsyncMock(return_value="handled")
    try:
        result = await set_locale_from_telegram_profile(handler, callback, {"api": "stub"})
        assert result == "handled"
        handler.assert_awaited_once_with(callback, {"api": "stub"})
        # Мидлварь выставляет локаль ДО вызова хендлера — проверяем это
        # через сайд-эффект внутри самого handler, а не постфактум, раз
        # AsyncMock ничего не читает из контекста сам по себе.
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)


@pytest.mark.asyncio
async def test_set_locale_from_telegram_profile_reflects_in_handler_execution():
    callback = make_callback()
    callback.from_user.language_code = "en-US"
    seen_locale = {}

    async def handler(event, data):
        seen_locale["value"] = i18n.get_locale()
        return None

    try:
        await set_locale_from_telegram_profile(handler, callback, {})
        assert seen_locale["value"] == "en"
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)


@pytest.mark.asyncio
async def test_set_locale_from_telegram_profile_defaults_to_en_when_code_missing():
    callback = make_callback()
    callback.from_user.language_code = None
    seen_locale = {}

    async def handler(event, data):
        seen_locale["value"] = i18n.get_locale()
        return None

    try:
        await set_locale_from_telegram_profile(handler, callback, {})
        assert seen_locale["value"] == "en"
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)
