"""Хендлеры /start, создание персонажа (gameplay_loop_mvp.md §1-2).

Правила игры — не здесь: живут в bot/handlers/character.py как кнопка на
экране статов (docs/notes.md, п.1), не как отдельная команда, чтобы не
плодить отдельные сообщения не в очереди с редактируемым боевым.
"""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.client import ApiClient, ApiError
from bot.handlers.character import allocation_keyboard, render_allocation_screen, render_stats_screen, stats_screen_keyboard

router = Router()

WELCOME_TEXT = (
    "🧙 Добро пожаловать в текстовую RPG!\n\n"
    "Ищи противников, сражайся на кубиках, качай персонажа."
)

RESET_CONFIRM_TEXT = (
    "⚠️ Точно обнулить персонажа?\n\n"
    "Статы, уровень и весь прогресс будут удалены безвозвратно — отменить это будет нельзя."
)


def _start_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Начать игру", callback_data="start_game")]]
    )


def _reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Да, удалить", callback_data="reset_confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="reset_cancel"),
            ]
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message, api: ApiClient) -> None:
    try:
        character = await api.get_character(message.from_user.id)
    except ApiError as error:
        if error.status_code != 404:
            raise
        # §1: персонажа ещё нет — предложить создать.
        await message.answer(WELCOME_TEXT, reply_markup=_start_game_keyboard())
        return

    # §1: персонаж уже есть — повторный /start не пересоздаёт его.
    await message.answer(WELCOME_TEXT)
    await message.answer(render_stats_screen(character), reply_markup=stats_screen_keyboard())


@router.callback_query(F.data == "start_game")
async def start_game(callback: CallbackQuery, api: ApiClient) -> None:
    try:
        character = await api.get_character(callback.from_user.id)
    except ApiError as error:
        if error.status_code != 404:
            raise
        character = await api.create_character(callback.from_user.id, callback.from_user.full_name)

    await callback.message.edit_text(
        render_allocation_screen(character, title="🧙 Создание героя"),
        reply_markup=allocation_keyboard(character, mode="creation"),
    )
    await callback.answer()


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    """Обнулить персонажа — в основном для тестирования, но без ограничения
    на окружение (docs/notes.md). Необратимо, поэтому только через
    подтверждение, а не с одного нажатия."""
    await message.answer(RESET_CONFIRM_TEXT, reply_markup=_reset_confirm_keyboard())


@router.callback_query(F.data == "reset_request")
async def reset_request(callback: CallbackQuery) -> None:
    """То же подтверждение, что и /reset, но с кнопки на экране прокачки
    (bot/handlers/character.py) — редактируем то же сообщение, а не шлём
    новое, как остальные экраны вне боя."""
    await callback.message.edit_text(RESET_CONFIRM_TEXT, reply_markup=_reset_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data == "reset_confirm")
async def reset_confirm(callback: CallbackQuery, api: ApiClient) -> None:
    await api.delete_character(callback.from_user.id)
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=_start_game_keyboard())
    await callback.answer("Персонаж удалён")


@router.callback_query(F.data == "reset_cancel")
async def reset_cancel(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Отменено.")
    await callback.answer()
