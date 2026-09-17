"""Тесты bot/handlers/combat.py."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.handlers.combat as combat_handlers
from bot.client import ApiError
from bot.handlers.combat import (
    confirm_fight,
    confirm_fight_auto,
    confirm_fight_fast,
    confirm_flee,
    flee_decision_continue,
    flee_decision_continue_auto,
    flee_decision_continue_fast,
    flee_decision_flee,
    refresh_after_battle,
    search_encounter,
    start_combat,
    take_turn,
)

pytestmark = pytest.mark.asyncio


def make_callback(data: str, user_id: int = 1) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def test_search_encounter_shows_initiative_button():
    callback = make_callback("search_encounter")
    api = AsyncMock()
    api.search_encounter.return_value = {"combat_session_id": 5, "enemy_type": "wolf", "text": "Ты наткнулся на волка."}

    await search_encounter(callback, api)

    api.search_encounter.assert_awaited_once_with(1)
    text = callback.message.edit_text.call_args.args[0]
    assert text == "Ты наткнулся на волка."
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "start_combat:5"


async def test_search_encounter_shows_friendly_alert_on_existing_session():
    # Раньше 409 от API падал необработанным исключением и "ронял" бота
    # (docs/notes.md) — например, если процесс перезапустили посреди боя.
    callback = make_callback("search_encounter")
    api = AsyncMock()
    api.search_encounter.side_effect = ApiError(409, "character already has an active combat session")

    await search_encounter(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once()
    assert callback.answer.call_args.kwargs.get("show_alert") is True


async def test_search_encounter_reraises_other_errors():
    callback = make_callback("search_encounter")
    api = AsyncMock()
    api.search_encounter.side_effect = ApiError(500, "boom")

    with pytest.raises(ApiError):
        await search_encounter(callback, api)


async def test_start_combat_shows_fight_or_flee_buttons():
    callback = make_callback("start_combat:5")
    api = AsyncMock()
    api.start_combat.return_value = {"combat_session_id": 5, "status": "awaiting_confirmation", "text": "..."}

    await start_combat(callback, api)

    api.start_combat.assert_awaited_once_with(1, 5)
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["confirm_fight:5", "confirm_flee:5", "confirm_fight_auto:5", "confirm_fight_fast:5"]


async def test_confirm_fight_shows_attack_button_when_player_goes_first():
    callback = make_callback("confirm_fight:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "result": None, "current_turn": "player", "text": "⚔️ Ты вступаешь в бой!"
    }

    await confirm_fight(callback, api)

    api.confirm_combat.assert_awaited_once_with(1, 5, "fight")
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    button = markup.inline_keyboard[0][0]
    assert button.text == "🎲 Атаковать"
    assert button.callback_data == "take_turn:5"


async def test_confirm_fight_shows_defend_button_when_enemy_goes_first():
    callback = make_callback("confirm_fight:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "result": None, "current_turn": "enemy", "text": "..."
    }

    await confirm_fight(callback, api)

    button = callback.message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "🛡️ Защищаться"


async def test_confirm_fight_auto_edits_message_on_every_turn_with_delay(monkeypatch):
    # Имитирует ручное нажатие: не одно сообщение в конце, а правка на
    # каждом ходу с паузой между ними (docs/notes.md, п.3).
    sleep_mock = AsyncMock()
    monkeypatch.setattr(combat_handlers.asyncio, "sleep", sleep_mock)

    callback = make_callback("confirm_fight_auto:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "result": None, "current_turn": "player", "text": "⚔️ Ты вступаешь в бой!"
    }
    api.take_turn.side_effect = [
        {"status": "active", "result": None, "current_turn": "enemy", "text": "Ход 1"},
        {"status": "active", "result": None, "current_turn": "player", "text": "Ход 2"},
        {"status": "finished", "result": "victory", "current_turn": "player", "text": "Ты победил!"},
    ]

    await confirm_fight_auto(callback, api)

    api.confirm_combat.assert_awaited_once_with(1, 5, "fight")
    assert api.take_turn.await_count == 3
    assert sleep_mock.await_count == 3
    for call in sleep_mock.await_args_list:
        assert call.args[0] == combat_handlers.AUTO_BATTLE_TURN_DELAY_SECONDS

    # entrance + 3 хода = 4 правки сообщения; answer() зовётся один раз, сразу после входа в бой.
    assert callback.message.edit_text.await_count == 4
    callback.answer.assert_awaited_once()

    first_text = callback.message.edit_text.call_args_list[0].args[0]
    assert first_text == "⚔️ Ты вступаешь в бой!\n\n3... 2... 1..."

    second_call = callback.message.edit_text.call_args_list[1]
    assert second_call.args[0] == "⚡ Автобой — ход 1\n\nХод 1"
    assert second_call.kwargs["reply_markup"] is None  # бой ещё активен — кнопок нет

    last_call = callback.message.edit_text.call_args_list[-1]
    assert last_call.args[0] == "⚡ Автобой — ход 3\n\nТы победил!"
    callback_datas = [btn.callback_data for row in last_call.kwargs["reply_markup"].inline_keyboard for btn in row]
    assert "search_encounter" in callback_datas  # финальный экран — с постбоевой клавиатурой


async def test_confirm_fight_auto_stops_at_flee_decision(monkeypatch):
    monkeypatch.setattr(combat_handlers.asyncio, "sleep", AsyncMock())

    callback = make_callback("confirm_fight_auto:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {"status": "active", "current_turn": "player", "text": "..."}
    api.take_turn.return_value = {
        "status": "awaiting_flee_decision", "current_turn": "player", "text": "⚠️ Шанс уйти живым!"
    }

    await confirm_fight_auto(callback, api)

    last_call = callback.message.edit_text.call_args_list[-1]
    callback_datas = [btn.callback_data for row in last_call.kwargs["reply_markup"].inline_keyboard for btn in row]
    # "Биться дальше" ведёт на _auto-вариант — бой шёл в автобою (docs/notes.md, п.3),
    # счётчик ходов (1) зашит в сам колбэк, чтобы возобновление продолжило сквозной счёт.
    assert callback_datas == ["flee_decision_flee:5", "flee_decision_continue_auto:5:1"]


async def test_flee_decision_continue_auto_resumes_autobattle_with_running_turn_count(monkeypatch):
    # После "Биться дальше" на паузе автобоя (turns_taken=3 в колбэке) бой
    # должен продолжиться автоматически, а не отдать ход обратно вручную —
    # и счёт ходов должен идти дальше с 4, не сбрасываться (docs/notes.md, п.3).
    monkeypatch.setattr(combat_handlers.asyncio, "sleep", AsyncMock())

    callback = make_callback("flee_decision_continue_auto:5:3")
    api = AsyncMock()
    api.flee_decision.return_value = {"status": "active", "current_turn": "enemy", "text": "Ход 4"}
    api.take_turn.return_value = {"status": "finished", "result": "victory", "text": "Ты победил!"}

    await flee_decision_continue_auto(callback, api)

    api.flee_decision.assert_awaited_once_with(1, 5, "continue")
    callback.answer.assert_awaited_once()

    first_call = callback.message.edit_text.call_args_list[0]
    assert first_call.args[0] == "⚡ Автобой — ход 4\n\nХод 4"
    assert first_call.kwargs["reply_markup"] is None  # бой ещё активен

    last_call = callback.message.edit_text.call_args_list[-1]
    assert last_call.args[0] == "⚡ Автобой — ход 5\n\nТы победил!"
    callback_datas = [btn.callback_data for row in last_call.kwargs["reply_markup"].inline_keyboard for btn in row]
    assert "search_encounter" in callback_datas


async def test_confirm_fight_fast_shows_only_the_final_result(monkeypatch):
    # "Показать результат" (docs/notes.md, п.26) — никакой анимации по
    # ходам, один вызов edit_text с итогом, без sleep между ходами.
    sleep_mock = AsyncMock()
    monkeypatch.setattr(combat_handlers.asyncio, "sleep", sleep_mock)  # не должен вызываться вовсе

    callback = make_callback("confirm_fight_fast:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {"status": "active", "current_turn": "player", "text": "..."}
    api.take_turn.side_effect = [
        {"status": "active", "current_turn": "enemy", "text": "Ход 1"},
        {"status": "active", "current_turn": "player", "text": "Ход 2"},
        {"status": "finished", "result": "victory", "text": "Ты победил!"},
    ]

    await confirm_fight_fast(callback, api)

    api.confirm_combat.assert_awaited_once_with(1, 5, "fight")
    assert api.take_turn.await_count == 3
    sleep_mock.assert_not_awaited()
    callback.answer.assert_awaited_once()

    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.call_args.args[0]
    assert text == "Ты победил!"
    callback_datas = [
        btn.callback_data
        for row in callback.message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard
        for btn in row
    ]
    assert "search_encounter" in callback_datas


async def test_confirm_fight_fast_stops_at_flee_decision():
    callback = make_callback("confirm_fight_fast:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {"status": "active", "current_turn": "player", "text": "..."}
    api.take_turn.return_value = {
        "status": "awaiting_flee_decision", "current_turn": "player", "text": "⚠️ Шанс уйти живым!"
    }

    await confirm_fight_fast(callback, api)

    callback.message.edit_text.assert_awaited_once()
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    # "Биться дальше" ведёт на _fast-вариант — бой шёл в режиме "Показать
    # результат" (docs/notes.md, п.26), без счёта ходов — он не отображается.
    assert callback_datas == ["flee_decision_flee:5", "flee_decision_continue_fast:5"]


async def test_flee_decision_continue_fast_resumes_silently_to_the_end():
    callback = make_callback("flee_decision_continue_fast:5")
    api = AsyncMock()
    api.flee_decision.return_value = {"status": "active", "current_turn": "enemy", "text": "..."}
    api.take_turn.return_value = {"status": "finished", "result": "victory", "text": "Ты победил!"}

    await flee_decision_continue_fast(callback, api)

    api.flee_decision.assert_awaited_once_with(1, 5, "continue")
    callback.answer.assert_awaited_once()

    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.call_args.args[0]
    assert text == "Ты победил!"


async def test_confirm_flee_shows_post_battle_buttons():
    callback = make_callback("confirm_flee:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {"status": "finished", "result": "player_fled", "text": "🏃 Тебе удалось уйти."}

    await confirm_flee(callback, api)

    api.confirm_combat.assert_awaited_once_with(1, 5, "flee")
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "refresh_after_battle" in callback_datas
    assert "search_encounter" in callback_datas
    assert "open_allocation" in callback_datas
    assert "show_rules" in callback_datas


async def test_take_turn_active_shows_turn_button():
    callback = make_callback("take_turn:5")
    api = AsyncMock()
    api.take_turn.return_value = {"status": "active", "current_turn": "enemy", "text": "..."}

    await take_turn(callback, api)

    button = callback.message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.callback_data == "take_turn:5"
    assert button.text == "🛡️ Защищаться"


async def test_take_turn_finished_shows_post_battle_buttons():
    callback = make_callback("take_turn:5")
    api = AsyncMock()
    api.take_turn.return_value = {"status": "finished", "result": "victory", "text": "⚔️ Ты победил!"}

    await take_turn(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["refresh_after_battle", "search_encounter", "open_allocation", "show_rules"]


async def test_take_turn_awaiting_flee_decision_shows_flee_buttons():
    callback = make_callback("take_turn:5")
    api = AsyncMock()
    api.take_turn.return_value = {
        "status": "awaiting_flee_decision", "text": "⚠️ Твоё HP критически низкое!"
    }

    await take_turn(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["flee_decision_flee:5", "flee_decision_continue:5"]


async def test_flee_decision_flee_shows_post_battle_buttons():
    callback = make_callback("flee_decision_flee:5")
    api = AsyncMock()
    api.flee_decision.return_value = {"status": "finished", "result": "defeat", "text": "💀 Ты пал..."}

    await flee_decision_flee(callback, api)

    api.flee_decision.assert_awaited_once_with(1, 5, "flee")
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "search_encounter" in callback_datas


async def test_flee_decision_continue_resumes_turn_cycle():
    callback = make_callback("flee_decision_continue:5")
    api = AsyncMock()
    api.flee_decision.return_value = {"status": "active", "current_turn": "player", "text": "..."}

    await flee_decision_continue(callback, api)

    api.flee_decision.assert_awaited_once_with(1, 5, "continue")
    button = callback.message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.callback_data == "take_turn:5"


async def test_refresh_after_battle_shows_hp_and_timer():
    callback = make_callback("refresh_after_battle")
    api = AsyncMock()
    api.get_character.return_value = {"hp_current": 15.0, "hp_max": 50.0, "hp_seconds_to_full": 35.0}

    await refresh_after_battle(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert text == "❤️ HP: 15/50\n⏳ Полное восстановление через: ~35 сек."
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "show_rules" in callback_datas  # экран "Обновить" тоже должен вести к правилам


async def test_refresh_after_battle_omits_timer_when_hp_full():
    callback = make_callback("refresh_after_battle")
    api = AsyncMock()
    api.get_character.return_value = {"hp_current": 50.0, "hp_max": 50.0, "hp_seconds_to_full": 0}

    await refresh_after_battle(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert text == "❤️ HP: 50/50"
