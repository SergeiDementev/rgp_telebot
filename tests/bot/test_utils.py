"""Тесты bot/utils.py — safe_edit_text."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.utils import safe_edit_text


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
