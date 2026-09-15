"""Общие мелкие утилиты для хендлеров бота."""

from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message


async def safe_edit_text(message: Message, text: str, *, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    """edit_text, но не падает, если контент не изменился.

    Нужно для кнопки "Обновить": если состояние с прошлого раза не
    поменялось (например, HP уже полностью восстановилось), Telegram
    отвечает ошибкой "message is not modified" на identical text+markup.
    Без обработки исключение прилетает раньше callback.answer() — спиннер
    на кнопке не гаснет, выглядит как зависание (docs/notes.md)."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message:
            raise
