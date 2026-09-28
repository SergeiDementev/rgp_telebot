"""Команда /language — выбор языка (ru/en) персонажа (docs/notes.md).

Инфраструктурный блок: пока меняет только значение в БД —
api/dependencies.py::get_localized_character читает его на стороне api/ и
выставляет текущую локаль (core/i18n.py) на время обработки запроса. Сами
тексты бота/боя ещё не переведены (следующие блоки) — с точки зрения
видимого результата эта команда пока ничего не меняет в текстах экранов,
кроме подтверждения после выбора.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.client import ApiClient
from bot.utils import get_character_or_prompt_start, safe_edit_text

router = Router()

LANGUAGE_PROMPT_TEXT = "🌐 Выбери язык / Choose language:"


def _language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Русский", callback_data="set_language:ru"),
                InlineKeyboardButton(text="English", callback_data="set_language:en"),
            ]
        ]
    )


@router.message(Command("language"))
async def cmd_language(message: Message) -> None:
    await message.answer(LANGUAGE_PROMPT_TEXT, reply_markup=_language_keyboard())


@router.callback_query(F.data.startswith("set_language:"))
async def set_language(callback: CallbackQuery, api: ApiClient) -> None:
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
    language = callback.data.split(":", 1)[1]
    await api.set_language(character["id"], language)
    confirmation = "✅ Язык переключён на русский." if language == "ru" else "✅ Language switched to English."
    await safe_edit_text(callback.message, confirmation, reply_markup=_language_keyboard())
    await callback.answer()
