"""Хендлеры боя: поиск противника → инициатива/обстоятельство → confirm →
цикл ходов → завершение (gameplay_loop_mvp.md §9).

Подписи кнопок "Атаковать"/"Защищаться" — косметика на стороне бота: обе
дёргают один и тот же POST /combat/{id}/turn (см. api/routers/combat.py) и
различаются только текстом, выбранным по `current_turn` из ответа сервера.
"""

import asyncio
from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.client import ApiClient, ApiError
from bot.utils import safe_edit_text

router = Router()

# Пауза между ходами в автобое (docs/notes.md, п.3) — достаточно медленно,
# чтобы реально видеть, что происходит (не мгновенный итог), и всё ещё с
# запасом от ориентировочного лимита Telegram на правки одного сообщения
# (~1/сек) — 429 "Too Many Requests" при такой паузе не грозит.
AUTO_BATTLE_TURN_DELAY_SECONDS = 1.5


def _session_id_from(callback_data: str) -> int:
    return int(callback_data.split(":", 1)[1])


def _session_id_and_turns_from(callback_data: str) -> tuple[int, int]:
    _, session_id_str, turns_str = callback_data.split(":")
    return int(session_id_str), int(turns_str)


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
    (docs/notes.md, п.33). Автобой и "Показать результат" никогда не строят
    клавиатуру через эту ветку _next_step_markup, пока бой активен (см. её
    докстринг) — кнопка структурно не может там появиться, отдельный флаг
    режима не нужен. Кнопка есть, только пока куплено хотя бы одно зелье
    нужного размера и лимит "раз за бой" (общий на оба размера) не сгорел;
    никогда — на ходу противника."""
    if response.get("current_turn") != "player" or response.get("potion_used_this_battle"):
        return []
    buttons = []
    if response.get("potions_small", 0) > 0:
        buttons.append(InlineKeyboardButton(text="🧪 Малое", callback_data=f"use_potion:{session_id}:small"))
    if response.get("potions_large", 0) > 0:
        buttons.append(InlineKeyboardButton(text="🧪 Большое", callback_data=f"use_potion:{session_id}:large"))
    return buttons


def _flee_choice_keyboard(session_id: int, *, mode: str = "manual", turns_taken: int = 0) -> InlineKeyboardMarkup:
    """`mode` — как боя продолжится после "Биться дальше", раз пауза могла
    случиться посреди авто- или быстрого боя (docs/notes.md, пп.3, 26), не
    только вручную:
    - "manual" — обычный цикл ход-за-ходом.
    - "auto" — возобновляет анимированный автобой; сквозной счёт ходов
      зашит в сам callback_data (бот не хранит состояние между сообщениями,
      больше протащить это число неоткуда).
    - "fast" — возобновляет тихий автобой без анимации; счёт ходов не
      нужен, он нигде не отображается."""
    if mode == "auto":
        continue_callback = f"flee_decision_continue_auto:{session_id}:{turns_taken}"
    elif mode == "fast":
        continue_callback = f"flee_decision_continue_fast:{session_id}"
    else:
        continue_callback = f"flee_decision_continue:{session_id}"
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


def _next_step_markup(session_id: int, response: dict, *, mode: str = "manual", turns_taken: int = 0) -> InlineKeyboardMarkup:
    """Выбор клавиатуры по статусу ответа confirm/turn/flee_decision. Ветка
    "status active" ниже — единственное место, строящее кнопку хода, и
    вызывается только из ручного боя (confirm_fight/take_turn/use_potion);
    автобой и "Показать результат" всегда проходят мимо неё, пока бой
    активен (reply_markup=None в цикле, см. _run_autobattle/_run_fast_battle) —
    поэтому кнопки зелий (см. _potion_buttons), добавленные здесь, структурно
    не могут появиться ни в автобою, ни в "Показать результат"."""
    if response["status"] == "finished":
        return _post_battle_keyboard()
    if response["status"] == "awaiting_flee_decision":
        return _flee_choice_keyboard(session_id, mode=mode, turns_taken=turns_taken)
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
            [
                InlineKeyboardButton(text="⚡ Автобой", callback_data=f"confirm_fight_auto:{session_id}"),
                InlineKeyboardButton(text="🏁 Показать результат", callback_data=f"confirm_fight_fast:{session_id}"),
            ],
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


async def _run_autobattle(
    callback: CallbackQuery, api: ApiClient, session_id: int, response: dict, turns_taken: int
) -> None:
    """Общий цикл автобоя (docs/notes.md, п.3) — переиспользуется и при
    первом входе в бой (confirm_fight_auto), и при возобновлении после
    паузы на решение "сбежать/биться дальше" (flee_decision_continue_auto).
    `response` — уже полученный результат последнего резолвнутого хода
    (его и показываем первым, только потом крутим цикл дальше), `turns_taken`
    — сквозной счётчик для подписи "⚡ Автобой — ход N", в т.ч. после паузы.

    Имитирует ручное нажатие: сообщение реально обновляется на каждом ходу
    с паузой между ними (AUTO_BATTLE_TURN_DELAY_SECONDS), не одним
    сообщением в конце — иначе не видно, что происходит. Останавливается на
    решении игрока (побег по HP) или на конце боя."""
    while True:
        battle_active = response["status"] == "active"
        text = f"⚡ Автобой — ход {turns_taken}\n\n{response['text']}"
        await callback.message.edit_text(
            text,
            reply_markup=None
            if battle_active
            else _next_step_markup(session_id, response, mode="auto", turns_taken=turns_taken),
        )
        if not battle_active:
            return
        await asyncio.sleep(AUTO_BATTLE_TURN_DELAY_SECONDS)
        response = await api.take_turn(callback.from_user.id, session_id)
        turns_taken += 1


async def _run_fast_battle(callback: CallbackQuery, api: ApiClient, session_id: int, response: dict) -> None:
    """Тихий вариант автобоя (docs/notes.md, п.25) — та же механика, что и
    `_run_autobattle`, только без анимации: крутит ходы молча, без пауз и
    без правки сообщения на каждом шаге, и один раз показывает результат —
    либо паузу на решение "сбежать/биться дальше", либо конец боя. Для
    коротких боёв с мышью, которые скучно читать по шагам."""
    while response["status"] == "active":
        response = await api.take_turn(callback.from_user.id, session_id)
    await callback.message.edit_text(response["text"], reply_markup=_next_step_markup(session_id, response, mode="fast"))


@router.callback_query(F.data.startswith("confirm_fight_auto:"))
async def confirm_fight_auto(callback: CallbackQuery, api: ApiClient) -> None:
    """Автобой — выбирается заново для каждого конкретного боя в момент
    решения "вступить/отступить", не общая настройка (docs/notes.md, п.3:
    решили не заводить под это отдельную колонку в Character — этот вариант
    проще и без изменений в БД)."""
    session_id = _session_id_from(callback.data)
    response = await api.confirm_combat(callback.from_user.id, session_id, "fight")
    # Отсчёт внизу сообщения — чтобы первая пауза перед автобоем не выглядела
    # зависанием: игрок читает "3... 2... 1...", и задержка перестаёт мешать
    # (docs/notes.md). Появляется только здесь, при самом входе в автобой.
    await callback.message.edit_text(f"{response['text']}\n\n3... 2... 1...")
    await callback.answer()  # отвечаем сразу — цикл ниже может растянуться на десятки секунд

    await asyncio.sleep(AUTO_BATTLE_TURN_DELAY_SECONDS)
    response = await api.take_turn(callback.from_user.id, session_id)
    await _run_autobattle(callback, api, session_id, response, turns_taken=1)


@router.callback_query(F.data.startswith("confirm_fight_fast:"))
async def confirm_fight_fast(callback: CallbackQuery, api: ApiClient) -> None:
    """"Показать результат" (docs/notes.md, п.25) — черновое название.
    Механика та же, что у автобоя (`confirm_fight_auto`), но без анимации:
    вступает в бой и сразу крутит ходы молча до паузы на решение или до
    конца боя, одной правкой сообщения показывает итог."""
    session_id = _session_id_from(callback.data)
    response = await api.confirm_combat(callback.from_user.id, session_id, "fight")
    await callback.answer()
    await _run_fast_battle(callback, api, session_id, response)


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
    п.3) — резолвит решение и сразу возобновляет автобой тем же циклом
    (_run_autobattle), а не отдаёт ход обратно вручную."""
    session_id, turns_taken = _session_id_and_turns_from(callback.data)
    response = await api.flee_decision(callback.from_user.id, session_id, "continue")
    await callback.answer()
    await _run_autobattle(callback, api, session_id, response, turns_taken=turns_taken + 1)


@router.callback_query(F.data.startswith("flee_decision_continue_fast:"))
async def flee_decision_continue_fast(callback: CallbackQuery, api: ApiClient) -> None:
    """Тот же выбор "Биться дальше", но бой шёл в режиме "Показать результат"
    (docs/notes.md, п.25) — резолвит решение и сразу возобновляет тихий
    автобой (`_run_fast_battle`), а не отдаёт ход обратно вручную."""
    session_id = _session_id_from(callback.data)
    response = await api.flee_decision(callback.from_user.id, session_id, "continue")
    await callback.answer()
    await _run_fast_battle(callback, api, session_id, response)


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
