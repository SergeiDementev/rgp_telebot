"""Тесты bot/handlers/language.py — команда /language."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.client import ApiError
from bot.handlers.language import LANGUAGE_PROMPT_TEXT, cmd_language, set_language
from core import i18n

pytestmark = pytest.mark.asyncio


def make_message() -> MagicMock:
    message = MagicMock()
    message.answer = AsyncMock()
    return message


def make_callback(data: str, user_id: int = 1) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def test_cmd_language_shows_ru_en_buttons():
    message = make_message()

    await cmd_language(message)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert args[0] == LANGUAGE_PROMPT_TEXT
    callback_datas = [btn.callback_data for row in kwargs["reply_markup"].inline_keyboard for btn in row]
    assert callback_datas == ["set_language:ru", "set_language:en"]


async def test_set_language_saves_choice_and_confirms_in_russian():
    callback = make_callback("set_language:ru")
    api = AsyncMock()
    api.get_character.return_value = {"id": 7, "language": "en"}

    await set_language(callback, api)

    api.set_language.assert_awaited_once_with(7, "ru")
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.call_args.args[0]
    assert "русский" in text.lower()
    callback.answer.assert_awaited_once()


async def test_set_language_saves_choice_and_confirms_in_english():
    callback = make_callback("set_language:en")
    api = AsyncMock()
    api.get_character.return_value = {"id": 7, "language": "ru"}

    await set_language(callback, api)

    api.set_language.assert_awaited_once_with(7, "en")
    text = callback.message.edit_text.call_args.args[0]
    assert "english" in text.lower()


async def test_set_language_confirmation_uses_newly_chosen_language_not_old():
    # docs/notes.md, блок 4 — локаль после get_character_or_prompt_start
    # отражает СТАРЫЙ character["language"]; подтверждение должно звучать
    # на НОВОМ выбранном языке (i18n.set_locale(language) явно после
    # api.set_language), а не на том, что было до переключения.
    callback = make_callback("set_language:en")
    api = AsyncMock()
    api.get_character.return_value = {"id": 7, "language": "ru"}
    try:
        await set_language(callback, api)
        assert i18n.get_locale() == "en"
        text = callback.message.edit_text.call_args.args[0]
        assert text == "✅ Language switched to English."
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)


async def test_set_language_confirms_exact_russian_text():
    callback = make_callback("set_language:ru")
    api = AsyncMock()
    api.get_character.return_value = {"id": 7, "language": "en"}

    await set_language(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert text == "✅ Язык переключён на русский."


async def test_set_language_prompts_start_when_character_missing():
    # Тот же паттерн грациозного 404, что и везде вне боя (docs/notes.md,
    # п.64) — /language можно набрать раньше, чем персонаж вообще создан.
    callback = make_callback("set_language:en")
    api = AsyncMock()
    api.get_character.side_effect = ApiError(404, "character not found")

    await set_language(callback, api)

    api.set_language.assert_not_called()
