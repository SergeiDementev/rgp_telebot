"""Тесты bot/utils.py — safe_edit_text, detect_language."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.utils import detect_language, safe_edit_text


def make_message() -> MagicMock:
    message = MagicMock()
    message.edit_text = AsyncMock()
    return message


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
