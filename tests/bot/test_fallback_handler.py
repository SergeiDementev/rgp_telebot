"""Тесты bot/handlers/fallback.py — заглушка на нераспознанный текст."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.fallback import unknown_text
from core import i18n

pytestmark = pytest.mark.asyncio


def make_message(text: str = "привет") -> MagicMock:
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


async def test_unknown_text_replies_with_buttons_only_hint():
    message = make_message("какой-то произвольный текст от игрока")

    await unknown_text(message)

    message.answer.assert_awaited_once_with("Управление в игре — только кнопками под сообщениями.")


async def test_unknown_text_does_not_forward_message_text_anywhere():
    # Текст сообщения нигде не читается и не передаётся дальше — ни в api,
    # ни в ответ. Единственный аргумент message.answer — фиксированная
    # строка-подсказка, не производная от message.text.
    message = make_message("secret payload")

    await unknown_text(message)

    reply_text = message.answer.call_args.args[0]
    assert "secret payload" not in reply_text


async def test_unknown_text_replies_in_english_locale():
    # docs/notes.md, блок 6 — хендлер не запрашивает персонажа, локаль на
    # момент выполнения выставляет диспетчерская мидлварь (bot/utils.py::
    # set_locale_from_telegram_profile, блок 4); здесь эмулируем это через
    # прямой i18n.set_locale(), как и в остальных тестах на обе локали.
    message = make_message("some random text")
    token = i18n.set_locale("en")
    try:
        await unknown_text(message)
        message.answer.assert_awaited_once_with("Use the buttons below the messages to control the game.")
    finally:
        i18n.reset_locale(token)
