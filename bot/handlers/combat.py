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
# чтобы реально видеть, что происходит (не мгновенный итог), и с большим
# запасом от ориентировочного лимита Telegram на правки одного сообщения
# (~1/сек) — 429 "Too Many Requests" при такой паузе не грозит.
AUTO_BATTLE_TURN_DELAY_SECONDS = 2.5


def _session_id_from(callback_data: str) -> int:
    return int(callback_data.split(":", 1)[1])


def _turn_button(session_id: int, current_turn: Optional[str]) -> InlineKeyboardButton:
    if current_turn == "enemy":
        return InlineKeyboardButton(text="🛡️ Защищаться", callback_data=f"take_turn:{session_id}")
    return InlineKeyboardButton(text="🎲 Атаковать", callback_data=f"take_turn:{session_id}")


def _flee_choice_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏃 Сбежать", callback_data=f"flee_decision_flee:{session_id}"),
                InlineKeyboardButton(
                    text="⚔️ Биться дальше", callback_data=f"flee_decision_continue:{session_id}"
                ),
            ]
        ]
    )


def _post_battle_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_after_battle")],
            [InlineKeyboardButton(text="🔍 Искать противника", callback_data="search_encounter")],
            [InlineKeyboardButton(text="📊 Прокачать статы", callback_data="open_allocation")],
            [InlineKeyboardButton(text="📜 Правила", callback_data="show_rules")],
        ]
    )


def _next_step_markup(session_id: int, response: dict) -> InlineKeyboardMarkup:
    """Выбор клавиатуры по статусу ответа confirm/turn/flee_decision."""
    if response["status"] == "finished":
        return _post_battle_keyboard()
    if response["status"] == "awaiting_flee_decision":
        return _flee_choice_keyboard(session_id)
    return InlineKeyboardMarkup(inline_keyboard=[[_turn_button(session_id, response.get("current_turn"))]])


@router.callback_query(F.data == "search_encounter")
async def search_encounter(callback: CallbackQuery, api: ApiClient) -> None:
    try:
        response = await api.search_encounter(callback.from_user.id)
    except ApiError as error:
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


@router.callback_query(F.data.startswith("confirm_fight_auto:"))
async def confirm_fight_auto(callback: CallbackQuery, api: ApiClient) -> None:
    """Автобой — выбирается заново для каждого конкретного боя в момент
    решения "вступить/отступить", не общая настройка (docs/notes.md, п.3:
    решили не заводить под это отдельную колонку в Character — этот вариант
    проще и без изменений в БД). Вступает в бой и сам крутит цикл ходов, пока
    не понадобится решение игрока (побег по HP) или бой не закончится —
    имитирует ручное нажатие: сообщение реально обновляется на каждом ходу
    с паузой между ними (AUTO_BATTLE_TURN_DELAY_SECONDS), не одним
    сообщением в конце — иначе не видно, что происходит."""
    session_id = _session_id_from(callback.data)
    response = await api.confirm_combat(callback.from_user.id, session_id, "fight")
    # Отсчёт внизу сообщения — чтобы первая пауза перед автобоем не выглядела
    # зависанием: игрок читает "3... 2... 1...", и задержка перестаёт мешать
    # (docs/notes.md). Появляется только здесь, при самом входе в автобой.
    await callback.message.edit_text(f"{response['text']}\n\n3... 2... 1...")
    await callback.answer()  # отвечаем сразу — цикл ниже может растянуться на десятки секунд

    turns_taken = 0
    while response["status"] == "active":
        await asyncio.sleep(AUTO_BATTLE_TURN_DELAY_SECONDS)
        response = await api.take_turn(callback.from_user.id, session_id)
        turns_taken += 1
        battle_still_active = response["status"] == "active"
        text = f"⚡ Автобой — ход {turns_taken}\n\n{response['text']}"
        await callback.message.edit_text(
            text, reply_markup=None if battle_still_active else _next_step_markup(session_id, response)
        )


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
