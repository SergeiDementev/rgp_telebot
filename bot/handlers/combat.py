"""Хендлеры боя: поиск противника → инициатива/обстоятельство → confirm →
цикл ходов → завершение (gameplay_loop_mvp.md §9).

Подписи кнопок "Атаковать"/"Защищаться" — косметика на стороне бота: обе
дёргают один и тот же POST /combat/{id}/turn (см. api/routers/combat.py) и
различаются только текстом, выбранным по `current_turn` из ответа сервера.
"💥 Мощный удар" (docs/combat_mechanics.md §3a) — тот же /turn с
power_attack=true в теле запроса, отдельная кнопка рядом с "Атаковать",
только на ходу игрока.
"""

from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.client import ApiClient, ApiError
from bot.handlers.character import (
    BOSS_LEVEL_REQUIREMENT,
    LARGE_POTION_CAP,
    SMALL_POTION_CAP,
    boss_button,
    render_stats_screen,
    stats_screen_keyboard,
)
from bot.utils import safe_edit_text

router = Router()


def _session_id_from(callback_data: str) -> int:
    return int(callback_data.split(":", 1)[1])


USE_POTION_ERROR_MESSAGES = {
    "already_used": "Зелье в этом бою уже использовано.",
    "not_owned": "У тебя нет такого зелья.",
}


def _attack_phase_buttons(session_id: int, current_turn: Optional[str]) -> list[InlineKeyboardButton]:
    """Кнопка(и) хода игрока. На ходу противника — только "Защищаться" (та
    же кнопка запускает /turn, подпись косметическая). На ходу игрока —
    выбор между обычной атакой и "💥 Мощный удар" (docs/combat_mechanics.md
    §3a) — доступен всегда, в любом бою, включая босса, без лимита."""
    if current_turn == "enemy":
        return [InlineKeyboardButton(text="🛡️ Защищаться", callback_data=f"take_turn:{session_id}")]
    return [
        InlineKeyboardButton(text="🎲 Атаковать", callback_data=f"take_turn:{session_id}"),
        InlineKeyboardButton(text="💥 Мощный удар", callback_data=f"take_turn_power:{session_id}"),
    ]


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
    """Кнопка финального босса (см. bot/handlers/character.py::boss_button)
    активна на любом уровне (docs/notes.md, п.58) — уровень сюда больше не
    нужен."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_after_battle")],
            [InlineKeyboardButton(text="🔍 Искать противника", callback_data="search_encounter")],
            [InlineKeyboardButton(text="👤 Меню игрока", callback_data="open_allocation")],
            [InlineKeyboardButton(text="📜 Правила", callback_data="show_rules")],
            [boss_button()],
        ]
    )


def _boss_victory_keyboard() -> InlineKeyboardMarkup:
    """Победа над финальным боссом — конец игры (docs/notes.md, п.36), не
    обычный постбоевой экран: единственный выход — обнулить персонажа и
    начать заново. Кнопка нарочно ведёт на тот же хендлер "reset_confirm:*",
    что и подтверждение "🗑 Обнулить персонажа" (bot/handlers/start.py) — тот
    уже делает ровно то, что нужно здесь (архивировать + пересоздать +
    показать экран создания, docs/notes.md п.41), без дополнительного
    диалога "точно?": само нажатие уже осознанный выбор, других кнопок на
    этом экране нет. Причина архивации в самом callback_data —
    "boss_victory", не "manual_reset" (для аналитики на сервере)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔄 Начать заново", callback_data="reset_confirm:boss_victory")]]
    )


def _initiative_prompt_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Определить инициативу", callback_data=f"start_combat:{session_id}")]
        ]
    )


def _potion_stock_text(potions_small: int, potions_large: int) -> str:
    return (
        f"🧪 Твой запас:\n"
        f"  Малое: {potions_small}/{SMALL_POTION_CAP}\n"
        f"  Большое: {potions_large}/{LARGE_POTION_CAP}"
    )


def _boss_challenge_keyboard(session_id: int) -> InlineKeyboardMarkup:
    """Экран входа в бой с боссом (docs/notes.md, п.51) — в отличие от
    обычной встречи, показывает запас зелий (бой с боссом без лимита "раз
    за бой", п.39, поэтому важно понимать, сколько их вообще есть) и даёт
    "⬅️ Назад": до инициативы отступить можно без всякого риска — сама
    встреча ещё ничего не решила, это не то же самое, что "🏃 Отступить"
    на экране после инициативы (там уже настоящая попытка побега). Порог
    уровня в подписи "Бросить вызов" — только подсказка (docs/notes.md,
    п.59), реальную проверку делает сервер на start_combat (п.58). Каждая
    кнопка на своей строке — "Бросить вызов" сверху, "Назад" снизу."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"⚔️ Бросить вызов (с {BOSS_LEVEL_REQUIREMENT} уровня)",
                callback_data=f"start_combat:{session_id}",
            )],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cancel_encounter:{session_id}")],
        ]
    )


def _confirmation_keyboard(session_id: int, enemy_type: str) -> InlineKeyboardMarkup:
    """Финальный босс — без пути назад после инициативы вообще (docs/notes.md,
    п.57): ни "🏃 Отступить" (из боя с ним нельзя сбежать, ни игроку, ни ему
    самому), ни "⚡ Автобой" (п.40 — зельём вслепую всё равно нельзя
    пользоваться). Единственный безрисковый выход — "⬅️ Назад" до инициативы
    (п.51, _boss_challenge_keyboard); нажал "⚔️ Бросить вызов" — бьёшься
    до конца."""
    if enemy_type == "boss":
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⚔️ Вступить в бой", callback_data=f"confirm_fight:{session_id}")]]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚔️ Вступить в бой", callback_data=f"confirm_fight:{session_id}"),
                InlineKeyboardButton(text="🏃 Отступить", callback_data=f"confirm_flee:{session_id}"),
            ],
            [InlineKeyboardButton(text="⚡ Автобой", callback_data=f"confirm_fight_auto:{session_id}")],
        ]
    )


def build_resume_text(resume: dict) -> str:
    """Текст восстановленного экрана (docs/notes.md, п.48/51) — тот же
    принцип, что и у клавиатуры ниже: экран с боссом до инициативы должен
    выглядеть так же, как и при свежем входе (с запасом зелий), не хуже."""
    text = resume["text"]
    if resume["status"] == "awaiting_initiative" and resume.get("enemy_type") == "boss":
        stock = _potion_stock_text(resume.get("potions_small", 0), resume.get("potions_large", 0))
        text = f"{text}\n\n{stock}"
    return text


def build_resume_keyboard(session_id: int, resume: dict) -> InlineKeyboardMarkup:
    """Клавиатура для восстановленного экрана боя (docs/notes.md, п.48) —
    например, после /start с потерянной клавиатурой (игрок удалил чат в
    Telegram, а CombatSession в БД осталась активной). Ветвится по status
    теми же клавиатурами, что и обычные хендлеры ниже — просто без нового
    действия, сюда ведёт /start, а не нажатие кнопки в этом же бою."""
    status = resume["status"]
    if status == "awaiting_initiative":
        if resume.get("enemy_type") == "boss":
            return _boss_challenge_keyboard(session_id)
        return _initiative_prompt_keyboard(session_id)
    if status == "awaiting_confirmation":
        return _confirmation_keyboard(session_id, resume["enemy_type"])
    # "active"/"awaiting_flee_decision" (и "finished" защитным дефолтом,
    # хотя эндпоинт /resume его не отдаёт) — та же логика, что и у обычного
    # ответа хода, восстановленный экран от них ничем не отличается.
    return _next_step_markup(session_id, resume)


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
    rows = [_attack_phase_buttons(session_id, response.get("current_turn"))]
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
    await callback.message.edit_text(response["text"], reply_markup=_initiative_prompt_keyboard(session_id))
    await callback.answer()


@router.callback_query(F.data == "search_boss_encounter")
async def search_boss_encounter(callback: CallbackQuery, api: ApiClient) -> None:
    """Целенаправленная встреча с финальным боссом (docs/notes.md, п.36) —
    кнопка на главном экране (bot/handlers/character.py::stats_screen_
    keyboard), а не через "Искать противника". Доступна на любом уровне
    (docs/notes.md, п.58) — уровневый гейт теперь на "⚔️ Бросить вызов"
    (см. start_combat), не здесь."""
    try:
        response = await api.search_boss_encounter(callback.from_user.id)
    except ApiError as error:
        if error.status_code != 409:
            raise
        await callback.answer("У тебя уже есть незавершённый бой — сначала заверши его.", show_alert=True)
        return
    session_id = response["combat_session_id"]
    # docs/notes.md, п.51 — запас зелий на экране входа (бой с боссом без
    # лимита "раз за бой", важно видеть, с чем реально входишь), плюс "⬅️
    # Назад" — до инициативы отступить можно без всякого риска.
    stock = _potion_stock_text(response["potions_small"], response["potions_large"])
    text = f"{response['text']}\n\n{stock}"
    await callback.message.edit_text(text, reply_markup=_boss_challenge_keyboard(session_id))
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_encounter:"))
async def cancel_encounter(callback: CallbackQuery, api: ApiClient) -> None:
    """"⬅️ Назад" на экране входа в бой, до инициативы (docs/notes.md,
    п.51) — отменяет встречу целиком (ничего ещё не произошло, нечего
    "доигрывать") и возвращает на главный экран персонажа."""
    session_id = _session_id_from(callback.data)
    try:
        await api.cancel_combat_session(callback.from_user.id, session_id)
    except ApiError as error:
        if error.status_code != 409:
            raise
        # Гонка — сессия уже не в статусе "до инициативы" (например, бой
        # уже начат с другого места). Отменять нечего, сообщаем и всё.
        await callback.answer("Бой уже начался — отменить нельзя.", show_alert=True)
        return
    character = await api.get_character(callback.from_user.id)
    await callback.message.edit_text(render_stats_screen(character), reply_markup=stats_screen_keyboard(character))
    await callback.answer()


@router.callback_query(F.data.startswith("start_combat:"))
async def start_combat(callback: CallbackQuery, api: ApiClient) -> None:
    """docs/notes.md, п.58 — уровневый порог для босса проверяется именно
    здесь (не на search_boss_encounter): сессия остаётся в
    "awaiting_initiative" при отказе, "⬅️ Назад" на предыдущем экране
    по-прежнему работает."""
    session_id = _session_id_from(callback.data)
    try:
        response = await api.start_combat(callback.from_user.id, session_id)
    except ApiError as error:
        if error.status_code != 403:
            raise
        await callback.answer("Финальный босс пока недоступен на этом уровне.", show_alert=True)
        return
    keyboard = _confirmation_keyboard(session_id, response.get("enemy_type"))
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
    try:
        response = await api.confirm_combat(callback.from_user.id, session_id, "flee")
    except ApiError as error:
        if error.detail != "flee_not_allowed":
            raise
        # Гонка/устаревшая клавиатура — у бота эта кнопка для босса и так не
        # показывается (docs/notes.md, п.57), сервер отклонил на всякий случай.
        await callback.answer("Из боя с этим противником нельзя отступить.", show_alert=True)
        return
    await callback.message.edit_text(response["text"], reply_markup=_post_battle_keyboard())
    await callback.answer()


async def _take_turn(callback: CallbackQuery, api: ApiClient, session_id: int, *, power_attack: bool) -> None:
    response = await api.take_turn(callback.from_user.id, session_id, power_attack=power_attack)
    await callback.message.edit_text(response["text"], reply_markup=_next_step_markup(session_id, response))
    await callback.answer()


@router.callback_query(F.data.startswith("take_turn:"))
async def take_turn(callback: CallbackQuery, api: ApiClient) -> None:
    session_id = _session_id_from(callback.data)
    await _take_turn(callback, api, session_id, power_attack=False)


@router.callback_query(F.data.startswith("take_turn_power:"))
async def take_turn_power(callback: CallbackQuery, api: ApiClient) -> None:
    session_id = _session_id_from(callback.data)
    await _take_turn(callback, api, session_id, power_attack=True)


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
