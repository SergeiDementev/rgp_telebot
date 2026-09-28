"""Общие мелкие утилиты для хендлеров бота."""

from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.client import ApiClient, ApiError
from core import i18n

# WELCOME_TEXT/start_game_keyboard живут здесь, а не в bot/handlers/start.py
# (откуда их естественно было бы ожидать), потому что get_character_or_
# prompt_start() ниже нужен и character.py, и combat.py, а те, в свою
# очередь, уже импортируются из start.py — переезд сюда единственный
# способ не завести цикл импортов (bot/utils.py ничего не импортирует из
# bot/handlers/*). bot/handlers/start.py по-прежнему реэкспортирует
# WELCOME_TEXT для обратной совместимости импортов из тестов.
WELCOME_TEXT = (
    "🧙 Добро пожаловать в текстовую RPG!\n\n"
    "Ищи противников, сражайся на кубиках, качай персонажа. "
    "Финальная цель — набраться сил и одолеть финального босса.\n\n"
    "🌐 /language — сменить язык / switch language"
)


def start_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Начать игру", callback_data="start_game")]]
    )


def detect_language(language_code: Optional[str]) -> str:
    """Язык персонажа по умолчанию при первом создании (docs/notes.md) —
    из message.from_user.language_code Telegram (двух-трёхбуквенный код,
    иногда с региональным суффиксом вроде "ru-RU"/"en-US", иногда
    отсутствует вовсе — Telegram его не гарантирует). "ru"/"ru-RU"/... →
    "ru", всё остальное, включая None, → "en"."""
    return "ru" if language_code is not None and language_code.startswith("ru") else "en"


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


async def get_character_or_prompt_start(callback: CallbackQuery, api: ApiClient) -> Optional[dict]:
    """Общая обёртка над api.get_character() для колбэков экранов вне боя.

    Персонажа может не быть — например, свежая БД после переезда на новую
    СУБД, или устаревшая клавиатура на старом сообщении в чате (docs/
    notes.md). Раньше каждый такой хендлер падал необработанным 404 —
    нажатие выглядело как зависание, без единого сообщения игроку. Теперь —
    то же приглашение "Начать игру", что и при самом первом /start
    (bot/handlers/start.py::cmd_start). Возвращает None, если персонажа нет
    (экран уже отредактирован здесь, вызывающий хендлер должен сразу
    return), иначе — сам персонаж.

    Заодно выставляет текущую локаль (core.i18n.set_locale) по
    character["language"] (docs/notes.md, блок 3) — единственная общая
    точка входа для character.py/combat.py/language.py, поэтому самое
    естественное место сделать это один раз, без лишнего запроса к API.
    bot/handlers/start.py не проходит через эту функцию (свой прямой
    api.get_character()) и выставляет локаль сама, тем же способом.
    `.get(..., DEFAULT_LOCALE)`, не прямой доступ по ключу — реальный API
    всегда отдаёт language (обязательное поле, api/schemas/character.py),
    но часть моков в тестах его не имитирует и это не повод падать здесь с
    KeyError."""
    try:
        character = await api.get_character(callback.from_user.id)
    except ApiError as error:
        if error.status_code != 404:
            raise
        await safe_edit_text(callback.message, WELCOME_TEXT, reply_markup=start_game_keyboard())
        await callback.answer()
        return None
    i18n.set_locale(character.get("language", i18n.DEFAULT_LOCALE))
    return character
