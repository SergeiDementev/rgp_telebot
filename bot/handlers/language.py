"""Команда /language — выбор языка (ru/en) персонажа (docs/notes.md).

Меняет значение в БД — api/dependencies.py::get_localized_character
читает его на стороне api/ и выставляет текущую локаль (core/i18n.py) на
время обработки запроса. Тексты боя (блок 2) и экраны персонажа/боевой UI
бота (блоки 3-4) теперь тоже переведены — после блока 4 видимый эффект
этой команды полный, кроме `content/rules.md` (следующий блок).

LANGUAGE_PROMPT_TEXT и подписи кнопок ("Русский"/"English") сознательно не
идут через core.i18n.t() — показываются ДО того, как язык выбран (или
переспрашиваются), поэтому нарочно двуязычны/показывают родные названия
языков, а не переводятся под текущую локаль."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.client import ApiClient
from bot.utils import get_character_or_prompt_start, safe_edit_text
from core import i18n

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
    # Локаль на этот момент — от СТАРОГО character["language"] (выставлена
    # get_character_or_prompt_start до строки выше); подтверждение должно
    # звучать на НОВОМ выбранном языке, поэтому переключаем явно, не
    # полагаясь на то, что уже стоит в контексте.
    i18n.set_locale(language)
    confirmation = i18n.t("language.confirmation")
    await safe_edit_text(callback.message, confirmation, reply_markup=_language_keyboard())
    await callback.answer()
