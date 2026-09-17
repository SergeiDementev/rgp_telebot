"""Хендлеры боя: поиск противника → инициатива/обстоятельство → confirm →
цикл ходов → завершение (gameplay_loop_mvp.md §9).

Подписи кнопок "Атаковать"/"Защищаться" — косметика на стороне бота: обе
дёргают один и тот же POST /combat/{id}/turn (см. api/routers/combat.py) и
различаются только текстом, выбранным по `current_turn` из ответа сервера.
"""

from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.client import ApiClient, ApiError
from bot.utils import safe_edit_text

router = Router()


def _session_id_from(callback_data: str) -> int:
    return int(callback_data.split(":", 1)[1])


USE_POTION_ERROR_MESSAGES = {
    "already_used": "Зелье в этом бою уже использовано.",
    "not_owned": "У тебя нет такого зелья.",
}


def _turn_button(session_id: int, current_turn: Optional[str]) -> InlineKeyboardButton:
    if current_turn == "enemy":
        return InlineKeyboardButton(text="🛡️ Защищаться", callback_data=f"take_turn:{session_id}")
    return InlineKeyboardButton(text="🎲 Атаковать", callback_data=f"take_turn:{session_id}")


def _potion_buttons(session_id: int, response: dict) -> list[InlineKeyboardButton]:
    """Зелье — явное действие кнопкой на этапе атаки, только в ручном бою
    (docs/notes.md, п.33). Автобой никогда не строит клавиатуру через эту
    ветку _next_step_markup, пока бой активен (см. её докстринг) — кнопка
    структурно не может там появиться, отдельный флаг режима не нужен.
    Кнопка есть, только пока куплено хотя бы одно зелье нужного размера и
    лимит "раз за бой" (общий на оба размера) не сгорел; никогда — на ходу
    противника."""
    if response.get("current_turn") != "player" or response.get("potion_used_this_battle"):
        return []
    buttons = []
    if response.get("potions_small", 0) > 0:
        buttons.append(InlineKeyboardButton(text="🧪 Малое", callback_data=f"use_potion:{session_id}:small"))
    if response.get("potions_large", 0) > 0:
        buttons.append(InlineKeyboardButton(text="🧪 Большое", callback_data=f"use_potion:{session_id}:large"))
    return buttons


def _flee_choice_keyboard(session_id: int, *, mode: str = "manual") -> InlineKeyboardMarkup:
    """`mode` — как бой продолжится после "Биться дальше", раз пауза могла
    случиться посреди автобоя (docs/notes.md, пп.3, 25, 34), не только
    вручную:
    - "manual" — обычный цикл ход-за-ходом.
    - "auto" — возобновляет автобой (тихо крутит ходы до конца/следующей
      паузы, без анимации по шагам — см. docs/notes.md, п.34: единственный
      оставшийся автоматический режим, раньше был "Показать результат")."""
    continue_callback = (
        f"flee_decision_continue_auto:{session_id}" if mode == "auto" else f"flee_decision_continue:{session_id}"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏃 Сбежать", callback_data=f"flee_decision_flee:{session_id}"),
                InlineKeyboardButton(text="⚔️ Биться дальше", callback_data=continue_callback),
            ]
        ]
    )


def _post_battle_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_after_battle")],
            [InlineKeyboardButton(text="🔍 Искать противника", callback_data="search_encounter")],
            [InlineKeyboardButton(text="👤 Меню игрока", callback_data="open_allocation")],
            [InlineKeyboardButton(text="📜 Правила", callback_data="show_rules")],
        ]
    )


def _boss_victory_keyboard() -> InlineKeyboardMarkup:
    """Победа над финальным боссом — конец игры (docs/notes.md, п.36), не
    обычный постбоевой экран: единственный выход — обнулить персонажа и
    начать заново. Кнопка нарочно ведёт на тот же callback_data
    "reset_confirm", что и подтверждение "🗑 Обнулить персонажа"
    (bot/handlers/start.py) — тот хендлер уже делает ровно то, что нужно
    здесь (удалить + пересоздать + показать экран создания), без
    дополнительного диалога "точно?": само нажатие уже осознанный выбор,
    других кнопок на этом экране нет."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔄 Начать заново", callback_data="reset_confirm")]]
    )


def _next_step_markup(session_id: int, response: dict, *, mode: str = "manual") -> InlineKeyboardMarkup:
    """Выбор клавиатуры по статусу ответа confirm/turn/flee_decision. Ветка
    "status active" ниже — единственное место, строящее кнопку хода, и
    вызывается только из ручного боя (confirm_fight/take_turn/use_potion);
    автобой всегда проходит мимо неё, пока бой активен (reply_markup=None в
    цикле, см. _run_autobattle) — поэтому кнопки зелий (см. _potion_buttons),
    добавленные здесь, структурно не могут появиться в автобою."""
    if response["status"] == "finished":
        if response.get("enemy_type") == "boss" and response.get("result") == "victory":
            return _boss_victory_keyboard()
        return _post_battle_keyboard()
    if response["status"] == "awaiting_flee_decision":
        return _flee_choice_keyboard(session_id, mode=mode)
    rows = [[_turn_button(session_id, response.get("current_turn"))]]
    potion_buttons = _potion_buttons(session_id, response)
    if potion_buttons:
        rows.append(potion_buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "search_encounter")
async def search_encounter(callback: CallbackQuery, api: ApiClient) -> None:
    try:
        response = await api.search_encounter(callback.from_user.id)
    except ApiError as error:
        if error.status_code != 409:
            raise
        # У персонажа уже есть незавершённая боевая сессия (см. api/routers/
        # encounter.py) — например, бот перезапустили посреди боя. Раньше
        # это падало необработанным исключением (docs/notes.md).
        await callback.answer("У тебя уже есть незавершённый бой — сначала заверши его.", show_alert=True)
        return
    session_id = response["combat_session_id"]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Определить инициативу", callback_data=f"start_combat:{session_id}")]
        ]
    )
    await callback.message.edit_text(response["text"], reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "search_boss_encounter")
async def search_boss_encounter(callback: CallbackQuery, api: ApiClient) -> None:
    """Целенаправленная встреча с финальным боссом (docs/notes.md, п.36) —
    кнопка на главном экране (bot/handlers/character.py::stats_screen_
    keyboard), а не через "Искать противника". Уровневый гейт бот уже
    проверил при показе кнопки (см. boss_locked), но сервер проверяет его
    тоже — на случай гонки (сообщение с кнопкой могло устареть)."""
    try:
        response = await api.search_boss_encounter(callback.from_user.id)
    except ApiError as error:
        if error.status_code == 403:
            await callback.answer("Финальный босс пока недоступен.", show_alert=True)
            return
        if error.status_code != 409:
            raise
        await callback.answer("У тебя уже есть незавершённый бой — сначала заверши его.", show_alert=True)
        return
    session_id = response["combat_session_id"]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Определить инициативу", callback_data=f"start_combat:{session_id}")]
        ]
    )
    await callback.message.edit_text(response["text"], reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("start_combat:"))
async def start_combat(callback: CallbackQuery, api: ApiClient) -> None:
    session_id = _session_id_from(callback.data)
    response = await api.start_combat(callback.from_user.id, session_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚔️ Вступить в бой", callback_data=f"confirm_fight:{session_id}"),
                InlineKeyboardButton(text="🏃 Отступить", callback_data=f"confirm_flee:{session_id}"),
            ],
            [InlineKeyboardButton(text="⚡ Автобой", callback_data=f"confirm_fight_auto:{session_id}")],
        ]
    )
    await callback.message.edit_text(response["text"], reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_fight:"))
async def confirm_fight(callback: CallbackQuery, api: ApiClient) -> None:
    session_id = _session_id_from(callback.data)
    response = await api.confirm_combat(callback.from_user.id, session_id, "fight")
    await callback.message.edit_text(response["text"], reply_markup=_next_step_markup(session_id, response))
    await callback.answer()


async def _run_autobattle(callback: CallbackQuery, api: ApiClient, session_id: int, response: dict) -> None:
    """Автобой (docs/notes.md, п.34 — было "Показать результат", п.25;
    старый анимированный автобой с паузой между ходами удалён — раз зельём
    всё равно нельзя пользоваться вне ручного боя, прокручивать сообщения
    по одному ходу не даёт игроку ничего, кроме ожидания). Крутит ходы
    молча, без пауз и без правки сообщения на каждом шаге, и один раз
    показывает результат — либо паузу на решение "сбежать/биться дальше",
    либо конец боя."""
    while response["status"] == "active":
        response = await api.take_turn(callback.from_user.id, session_id)
    await callback.message.edit_text(response["text"], reply_markup=_next_step_markup(session_id, response, mode="auto"))


@router.callback_query(F.data.startswith("confirm_fight_auto:"))
async def confirm_fight_auto(callback: CallbackQuery, api: ApiClient) -> None:
    """Автобой — выбирается заново для каждого конкретного боя в момент
    решения "вступить/отступить", не общая настройка (docs/notes.md, п.3:
    решили не заводить под это отдельную колонку в Character — этот вариант
    проще и без изменений в БД)."""
    session_id = _session_id_from(callback.data)
    response = await api.confirm_combat(callback.from_user.id, session_id, "fight")
    await callback.answer()
    await _run_autobattle(callback, api, session_id, response)


@router.callback_query(F.data.startswith("confirm_flee:"))
async def confirm_flee(callback: CallbackQuery, api: ApiClient) -> None:
    session_id = _session_id_from(callback.data)
    response = await api.confirm_combat(callback.from_user.id, session_id, "flee")
    await callback.message.edit_text(response["text"], reply_markup=_post_battle_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("take_turn:"))
async def take_turn(callback: CallbackQuery, api: ApiClient) -> None:
    session_id = _session_id_from(callback.data)
    response = await api.take_turn(callback.from_user.id, session_id)
    await callback.message.edit_text(response["text"], reply_markup=_next_step_markup(session_id, response))
    await callback.answer()


@router.callback_query(F.data.startswith("use_potion:"))
async def use_potion(callback: CallbackQuery, api: ApiClient) -> None:
    """Зелье — явное действие игрока кнопкой на его ходу атаки, только в
    ручном бою (docs/notes.md, п.33). Заменяет атаку в этот ход — сервер
    сам передаёт ход противнику (api/routers/combat.py::_use_potion)."""
    _, session_id_str, size = callback.data.split(":")
    session_id = int(session_id_str)
    try:
        response = await api.use_potion(callback.from_user.id, session_id, size)
    except ApiError as error:
        message = USE_POTION_ERROR_MESSAGES.get(error.detail, "Сейчас нельзя использовать зелье.")
        await callback.answer(message, show_alert=True)
        return
    await callback.message.edit_text(response["text"], reply_markup=_next_step_markup(session_id, response))
    await callback.answer()


@router.callback_query(F.data.startswith("flee_decision_flee:"))
async def flee_decision_flee(callback: CallbackQuery, api: ApiClient) -> None:
    session_id = _session_id_from(callback.data)
    response = await api.flee_decision(callback.from_user.id, session_id, "flee")
    await callback.message.edit_text(response["text"], reply_markup=_post_battle_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("flee_decision_continue:"))
async def flee_decision_continue(callback: CallbackQuery, api: ApiClient) -> None:
    session_id = _session_id_from(callback.data)
    response = await api.flee_decision(callback.from_user.id, session_id, "continue")
    await callback.message.edit_text(response["text"], reply_markup=_next_step_markup(session_id, response))
    await callback.answer()


@router.callback_query(F.data.startswith("flee_decision_continue_auto:"))
async def flee_decision_continue_auto(callback: CallbackQuery, api: ApiClient) -> None:
    """Тот же выбор "Биться дальше", но бой шёл в автобою (docs/notes.md,
    п.34) — резолвит решение и сразу возобновляет автобой тем же циклом
    (_run_autobattle), а не отдаёт ход обратно вручную."""
    session_id = _session_id_from(callback.data)
    response = await api.flee_decision(callback.from_user.id, session_id, "continue")
    await callback.answer()
    await _run_autobattle(callback, api, session_id, response)


@router.callback_query(F.data == "refresh_after_battle")
async def refresh_after_battle(callback: CallbackQuery, api: ApiClient) -> None:
    """§8 gameplay_loop_mvp.md: пересчитывает HP по формуле, переотправляет
    актуальные цифры. Упрощение: отдельный статус-блок, а не буквально то же
    сообщение — заголовок исхода боя ("Ты победил...") был частью разового
    текста turn-ответа и нигде не хранится; реконструировать его в боте
    означало бы дублировать решение api/rendering.py о формулировке исхода."""
    character = await api.get_character(callback.from_user.id)
    lines = [f"❤️ HP: {character['hp_current']:.0f}/{character['hp_max']:.0f}"]
    if character["hp_seconds_to_full"] > 0:
        lines.append(f"⏳ Полное восстановление через: ~{character['hp_seconds_to_full']:.0f} сек.")
    await safe_edit_text(callback.message, "\n".join(lines), reply_markup=_post_battle_keyboard())
    await callback.answer()
