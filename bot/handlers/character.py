"""Хендлеры экрана статов и прокачки (gameplay_loop_mvp.md §4-5).

Один и тот же экран/клавиатура прокачки используется и при создании
персонажа (mode="creation" — кнопка "Начать приключение"), и при обычном
левел-апе (mode="levelup" — кнопка "Назад") — механика идентична, разный
только заголовок и кнопка выхода (§5). Различие живёт в callback_data
("allocate:<stat>" / "create_allocate:<stat>"), не в состоянии на сервере —
бот сам ничего не хранит между сообщениями.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.client import ApiClient, ApiError

router = Router()


def render_stats_screen(character: dict) -> str:
    """§4: переиспользуемый экран статов персонажа."""
    return (
        f"🧙 {character['nickname']}\n"
        f"🏅 Уровень: {character['level']}\n"
        f"❤️ HP: {character['hp_current']:.0f}/{character['hp_max']:.0f}\n"
        f"💪 Сила: {character['strength']}\n"
        f"🤸 Ловкость: {character['agility']}\n"
        f"🍀 Удача: {character['luck']}\n"
        f"🏆 Победные очки: {character['victory_points']} "
        f"(до след. уровня: {character['points_to_next_level']})"
    )


def stats_screen_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Искать противника", callback_data="search_encounter")],
            [InlineKeyboardButton(text="📊 Прокачать статы", callback_data="open_allocation")],
        ]
    )


def render_allocation_screen(character: dict, *, title: str) -> str:
    lines = [
        title,
        f"Доступно очков: {character['unspent_stat_points']}",
        "",
        f"💪 Сила: {character['strength']}",
        f"🤸 Ловкость: {character['agility']}",
        f"🍀 Удача: {character['luck']}",
        f"❤️ Здоровье: {character['vitality']}  (HP max: {character['hp_max']:.0f})",
    ]
    if character["unspent_stat_points"] == 0:
        lines.append("")
        lines.append(
            "Нет свободных очков. Получишь ещё при следующем уровне "
            f"(до след. уровня: {character['points_to_next_level']} победных очков)."
        )
    return "\n".join(lines)


def allocation_keyboard(character: dict, *, mode: str) -> InlineKeyboardMarkup:
    """mode: "creation" | "levelup" — определяет префикс callback_data и нижнюю кнопку."""
    prefix = "create_allocate" if mode == "creation" else "allocate"
    rows = []
    if character["unspent_stat_points"] > 0:
        rows.append(
            [
                InlineKeyboardButton(text="+1 Сила", callback_data=f"{prefix}:strength"),
                InlineKeyboardButton(text="+1 Ловкость", callback_data=f"{prefix}:agility"),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="+1 Удача", callback_data=f"{prefix}:luck"),
                InlineKeyboardButton(text="+1 Здоровье", callback_data=f"{prefix}:vitality"),
            ]
        )
    if mode == "creation":
        rows.append([InlineKeyboardButton(text="✅ Начать приключение", callback_data="finish_creation")])
    else:
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_stats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "open_allocation")
async def open_allocation(callback: CallbackQuery, api: ApiClient) -> None:
    character = await api.get_character(callback.from_user.id)
    await callback.message.edit_text(
        render_allocation_screen(character, title="📊 Прокачка характеристик"),
        reply_markup=allocation_keyboard(character, mode="levelup"),
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_stats")
async def back_to_stats(callback: CallbackQuery, api: ApiClient) -> None:
    character = await api.get_character(callback.from_user.id)
    await callback.message.edit_text(render_stats_screen(character), reply_markup=stats_screen_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("allocate:"))
async def allocate_levelup(callback: CallbackQuery, api: ApiClient) -> None:
    stat = callback.data.split(":", 1)[1]
    character = await api.get_character(callback.from_user.id)
    try:
        result = await api.allocate_point(character["id"], stat)
    except ApiError:
        await callback.answer("Не осталось свободных очков", show_alert=True)
        return
    updated = result["character"]
    await callback.message.edit_text(
        render_allocation_screen(updated, title="📊 Прокачка характеристик"),
        reply_markup=allocation_keyboard(updated, mode="levelup"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("create_allocate:"))
async def allocate_creation(callback: CallbackQuery, api: ApiClient) -> None:
    stat = callback.data.split(":", 1)[1]
    character = await api.get_character(callback.from_user.id)
    try:
        result = await api.allocate_point(character["id"], stat)
    except ApiError:
        await callback.answer("Не осталось свободных очков", show_alert=True)
        return
    updated = result["character"]
    await callback.message.edit_text(
        render_allocation_screen(updated, title="🧙 Создание героя"),
        reply_markup=allocation_keyboard(updated, mode="creation"),
    )
    await callback.answer()


@router.callback_query(F.data == "finish_creation")
async def finish_creation(callback: CallbackQuery, api: ApiClient) -> None:
    character = await api.get_character(callback.from_user.id)
    await callback.message.edit_text(render_stats_screen(character), reply_markup=stats_screen_keyboard())
    await callback.answer()
