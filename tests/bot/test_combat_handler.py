"""Тесты bot/handlers/combat.py."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.combat import (
    confirm_fight,
    confirm_flee,
    flee_decision_continue,
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


async def test_start_combat_shows_fight_or_flee_buttons():
    callback = make_callback("start_combat:5")
    api = AsyncMock()
    api.start_combat.return_value = {"combat_session_id": 5, "status": "awaiting_confirmation", "text": "..."}

    await start_combat(callback, api)

    api.start_combat.assert_awaited_once_with(1, 5)
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["confirm_fight:5", "confirm_flee:5"]


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
