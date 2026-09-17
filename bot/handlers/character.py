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
from bot.rules_content import RULES_MENU_TITLE, RULES_SECTIONS
from bot.utils import safe_edit_text

router = Router()

# Дублирует core/economy.py (docs/notes.md, п.30) — бот принципиально не
# импортирует core/ (тонкий клиент, см. docs/README.md), но подписи кнопок
# покупки должны показывать цену/кап без лишнего запроса к API. При
# изменении цен/капов в core/economy.py синхронизировать вручную — тот же
# паттерн, что уже есть для DODGE_K и т.п. между scripts/simulate_combat.py
# и api/routers/combat.py.
SMALL_POTION_PRICE = 8
LARGE_POTION_PRICE = 50
SMALL_POTION_CAP = 5
LARGE_POTION_CAP = 3

LOOT_ITEM_NAMES_RU = {
    "mouse_pelt": "Мышиная шкурка",
    "mouse_tail": "Мышиный хвост",
    "wolf_fang": "Клык волка",
    "wolf_pelt": "Шкура волка",
    "boar_tusk": "Клык кабана",
    "boar_hide": "Шкура кабана",
}

# Цена продажи за штуку (core/economy.py::LOOT_ITEM_PRICES) — для строки
# лута на экране "Меню игрока" (docs/notes.md), та же дублирующая логика.
LOOT_ITEM_PRICES = {
    "mouse_pelt": 2,
    "mouse_tail": 5,
    "wolf_fang": 8,
    "wolf_pelt": 20,
    "boar_tusk": 20,
    "boar_hide": 50,
}

BUY_POTION_ERROR_MESSAGES = {
    "not_enough_gold": "Не хватает золота.",
    "cap_reached": "Уже максимум зелий этого размера.",
}

MENU_SCREEN_TITLE = "👤 Меню игрока"


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
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_stats")],
            [InlineKeyboardButton(text="🔍 Искать противника", callback_data="search_encounter")],
            [InlineKeyboardButton(text=MENU_SCREEN_TITLE, callback_data="open_allocation")],
            [InlineKeyboardButton(text="📜 Правила", callback_data="show_rules")],
        ]
    )


def rules_menu_keyboard() -> InlineKeyboardMarkup:
    """content/rules.md целиком не влезает в лимит сообщения Telegram (4096
    символов) — показываем меню разделов, а не текст сразу (bot/rules_content.py)."""
    rows = [
        [InlineKeyboardButton(text=title, callback_data=f"rules_section:{index}")]
        for index, (title, _body) in enumerate(RULES_SECTIONS)
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_stats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rules_section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ К списку разделов", callback_data="show_rules")]])


def _render_loot_item(name: str, count: int) -> str:
    display_name = LOOT_ITEM_NAMES_RU.get(name, name)
    price = LOOT_ITEM_PRICES.get(name, 0)
    if count == 1:
        return f"{display_name} ({price} зол.)"
    return f"{display_name} ×{count} ({price * count} зол.)"


def _render_loot_line(loot: dict) -> str:
    items = [_render_loot_item(name, count) for name, count in loot.items() if count > 0]
    return f"📦 Лут: {', '.join(items)}" if items else "📦 Лут: пока нет"


def _render_potions_line(potions_small: int, potions_large: int) -> str:
    parts = []
    if potions_small > 0:
        parts.append(f"Малое ×{potions_small}")
    if potions_large > 0:
        parts.append(f"Большое ×{potions_large}")
    return f"🧪 Зелья: {', '.join(parts)}" if parts else "🧪 Зелья: пока нет"


def render_allocation_screen(character: dict, *, title: str, mode: str) -> str:
    """mode="creation" — прежний простой макет (у нового персонажа физически
    не может быть золота/лута/зелий, docs/gameplay_loop_mvp.md §5). mode=
    "levelup" — "Меню игрока" (docs/notes.md, п.30): статы → победные
    очки/золото/очки прокачки → лут → зелья."""
    if mode == "creation":
        return "\n".join(
            [
                title,
                f"Осталось очков: {character['unspent_stat_points']}",
                "",
                f"💪 Сила: {character['strength']}",
                f"🤸 Ловкость: {character['agility']}",
                f"🍀 Удача: {character['luck']}",
                f"❤️ Здоровье: {character['vitality']}  (HP max: {character['hp_max']:.0f})",
            ]
        )

    lines = [
        f"🏅 Уровень: {character['level']}",
        f"💪 Сила: {character['strength']}",
        f"🤸 Ловкость: {character['agility']}",
        f"🍀 Удача: {character['luck']}",
        f"❤️ Здоровье: {character['vitality']}  (HP max: {character['hp_max']:.0f})",
        "",
        f"🏆 Победные очки: {character['victory_points']} (до след. уровня: {character['points_to_next_level']})",
    ]
    if character["unspent_stat_points"] > 0:
        lines.append(f"Доступно очков прокачки: {character['unspent_stat_points']}")
    lines.append("")
    lines.append(f"💰 Золото: {character['gold']}")
    lines.append("")
    lines.append(_render_loot_line(character["loot"]))
    lines.append(_render_potions_line(character["potions_small"], character["potions_large"]))
    return "\n".join(lines)


def _buy_potion_button(size: str, potions_owned: int) -> InlineKeyboardButton:
    if size == "large":
        name, price, cap = "большое", LARGE_POTION_PRICE, LARGE_POTION_CAP
    else:
        name, price, cap = "малое", SMALL_POTION_PRICE, SMALL_POTION_CAP
    status = "уже максимум" if potions_owned >= cap else f"{price} зол."
    return InlineKeyboardButton(text=f"🧪 Купить {name} ({status})", callback_data=f"buy_potion:{size}")


def allocation_keyboard(character: dict, *, mode: str) -> InlineKeyboardMarkup:
    """mode: "creation" | "levelup" — определяет префикс callback_data и
    нижние кнопки. Три разных паттерна видимости на экране "Меню игрока"
    (docs/gameplay_loop_mvp.md §5) — не унифицировать:
    - "+1 <стат>" — исчезает целиком, если очков нет (как и раньше).
    - "Продать весь лут" — исчезает целиком, если лут пуст.
    - "Купить зелье" — ВСЕГДА видима, меняется только подпись (цена / "уже
      максимум") — покупка часто цель, к которой копится золото, прятать
      кнопку означало бы прятать сам ориентир."""
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
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if any(count > 0 for count in character["loot"].values()):
        rows.append([InlineKeyboardButton(text="💰 Продать весь лут", callback_data="sell_loot")])
    # Каждая кнопка зелья — своей строкой, не парой в одной (docs/notes.md):
    # текст с ценой не помещался при двух кнопках в ряд.
    rows.append([_buy_potion_button("small", character["potions_small"])])
    rows.append([_buy_potion_button("large", character["potions_large"])])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_stats")])
    # Только на экране "Меню игрока", не при создании — во время creation
    # ещё нечего обнулять (docs/notes.md, п.12).
    rows.append([InlineKeyboardButton(text="🗑 Обнулить персонажа", callback_data="reset_request")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "show_rules")
async def show_rules(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        f"📖 <b>{RULES_MENU_TITLE}</b>\n\nВыбери раздел:", reply_markup=rules_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rules_section:"))
async def show_rules_section(callback: CallbackQuery) -> None:
    index = int(callback.data.split(":", 1)[1])
    title, body = RULES_SECTIONS[index]
    await callback.message.edit_text(f"<b>{title}</b>\n\n{body}", reply_markup=rules_section_keyboard())
    await callback.answer()


@router.callback_query(F.data == "open_allocation")
async def open_allocation(callback: CallbackQuery, api: ApiClient) -> None:
    character = await api.get_character(callback.from_user.id)
    await callback.message.edit_text(
        render_allocation_screen(character, title=MENU_SCREEN_TITLE, mode="levelup"),
        reply_markup=allocation_keyboard(character, mode="levelup"),
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_stats")
@router.callback_query(F.data == "refresh_stats")
async def back_to_stats(callback: CallbackQuery, api: ApiClient) -> None:
    character = await api.get_character(callback.from_user.id)
    await safe_edit_text(callback.message, render_stats_screen(character), reply_markup=stats_screen_keyboard())
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
        render_allocation_screen(updated, title=MENU_SCREEN_TITLE, mode="levelup"),
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
        render_allocation_screen(updated, title="🧙 Создание героя", mode="creation"),
        reply_markup=allocation_keyboard(updated, mode="creation"),
    )
    await callback.answer()


@router.callback_query(F.data == "finish_creation")
async def finish_creation(callback: CallbackQuery, api: ApiClient) -> None:
    character = await api.get_character(callback.from_user.id)
    await callback.message.edit_text(render_stats_screen(character), reply_markup=stats_screen_keyboard())
    await callback.answer()


@router.callback_query(F.data == "sell_loot")
async def sell_loot(callback: CallbackQuery, api: ApiClient) -> None:
    character = await api.get_character(callback.from_user.id)
    result = await api.sell_loot(character["id"])
    updated = result["character"]
    await callback.message.edit_text(
        render_allocation_screen(updated, title=MENU_SCREEN_TITLE, mode="levelup"),
        reply_markup=allocation_keyboard(updated, mode="levelup"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_potion:"))
async def buy_potion(callback: CallbackQuery, api: ApiClient) -> None:
    size = callback.data.split(":", 1)[1]
    character = await api.get_character(callback.from_user.id)
    try:
        result = await api.buy_potion(character["id"], size)
    except ApiError as error:
        message = BUY_POTION_ERROR_MESSAGES.get(error.detail, "Не удалось купить зелье.")
        await callback.answer(message, show_alert=True)
        return
    updated = result["character"]
    await callback.message.edit_text(
        render_allocation_screen(updated, title=MENU_SCREEN_TITLE, mode="levelup"),
        reply_markup=allocation_keyboard(updated, mode="levelup"),
    )
    await callback.answer()
