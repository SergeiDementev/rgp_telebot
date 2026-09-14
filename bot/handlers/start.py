"""Хендлеры /start, /rules, создание персонажа (gameplay_loop_mvp.md §1-2)."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.client import ApiClient, ApiError
from bot.handlers.character import allocation_keyboard, render_allocation_screen, render_stats_screen, stats_screen_keyboard

router = Router()

WELCOME_TEXT = (
    "🧙 Добро пожаловать в текстовую RPG!\n\n"
    "Ищи противников, сражайся на кубиках, качай персонажа.\n"
    "Полные правила — по команде /rules."
)

RULES_TEXT = (
    "📖 Правила игры\n\n"
    "Характеристики:\n"
    "❤️ HP — очки здоровья. 0 — поражение.\n"
    "💪 Сила — урон от удара, растёт предсказуемо.\n"
    "🤸 Ловкость — шанс полностью увернуться от удара (либо весь урон, либо ноль).\n"
    "🍀 Удача — шанс на двойной удар за ход и на побег при критичном HP.\n\n"
    "Бой:\n"
    "1. Определяется, кто ходит первым, и случайное обстоятельство — баф или дебаф "
    "Силы одной из сторон на весь бой.\n"
    "2. Можно принять бой или отступить (это тоже безответный удар противника — "
    "уйти чисто не гарантировано).\n"
    "3. Ходы идут по очереди: атака (Сила) → уворот противника (Ловкость) → урон. "
    "Иногда срабатывает двойной удар (Удача).\n"
    "4. Если твоё HP становится критически низким, может открыться шанс сбежать — "
    "но это тоже ставка: противник бьёт без защиты вдогонку.\n\n"
    "Награда — только за победу. Победные очки не теряются при поражении или побеге.\n\n"
    "Прокачка: победные очки копятся и открывают уровни, на каждом уровне — очки "
    "прокачки, которые сам распределяешь по характеристикам.\n\n"
    "HP восстанавливается со временем автоматически — специально ждать не нужно."
)


def _start_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Начать игру", callback_data="start_game")]]
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


@router.message(Command("rules"))
async def cmd_rules(message: Message) -> None:
    await message.answer(RULES_TEXT)


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
