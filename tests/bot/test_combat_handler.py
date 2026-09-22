"""Тесты bot/handlers/combat.py."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.client import ApiError
from bot.handlers.combat import (
    build_resume_keyboard,
    build_resume_text,
    cancel_encounter,
    confirm_fight,
    confirm_fight_auto,
    confirm_flee,
    flee_decision_continue,
    flee_decision_continue_auto,
    flee_decision_flee,
    refresh_after_battle,
    search_boss_encounter,
    search_encounter,
    start_combat,
    take_turn,
    take_turn_power,
    use_potion,
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


async def test_search_boss_encounter_shows_potion_stock_and_challenge_buttons():
    # docs/notes.md, п.51 — экран входа в бой с боссом показывает запас
    # зелий и даёт "⬅️ Назад" (безрисковая отмена до инициативы), в отличие
    # от обычной встречи (только "Определить инициативу", без счётчика).
    callback = make_callback("search_boss_encounter")
    api = AsyncMock()
    api.search_boss_encounter.return_value = {
        "combat_session_id": 9, "enemy_type": "boss", "text": "Ты входишь в чертог Лесного Короля.",
        "potions_small": 2, "potions_large": 1,
    }

    await search_boss_encounter(callback, api)

    api.search_boss_encounter.assert_awaited_once_with(1)
    text = callback.message.edit_text.call_args.args[0]
    assert text == (
        "Ты входишь в чертог Лесного Короля.\n\n"
        "🧪 Твой запас:\n"
        "  Малое: 2/5\n"
        "  Большое: 1/3"
    )
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    # docs/notes.md, п.59 — каждая кнопка на своей строке, "Бросить вызов"
    # сверху, "Назад" снизу; подпись напоминает порог уровня (подсказка, не
    # гейт — сервер всё равно проверит его сам на start_combat).
    assert len(markup.inline_keyboard) == 2
    assert markup.inline_keyboard[0][0].callback_data == "start_combat:9"
    assert "9 уровня" in markup.inline_keyboard[0][0].text
    assert markup.inline_keyboard[1][0].callback_data == "cancel_encounter:9"


async def test_search_boss_encounter_shows_alert_on_existing_session():
    callback = make_callback("search_boss_encounter")
    api = AsyncMock()
    api.search_boss_encounter.side_effect = ApiError(409, "character already has an active combat session")

    await search_boss_encounter(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once()
    assert callback.answer.call_args.kwargs.get("show_alert") is True


async def test_start_combat_against_boss_shows_alert_when_level_too_low():
    # docs/notes.md, п.58 — уровневый гейт перенесён на "⚔️ Бросить вызов"
    # (start_combat), search_boss_encounter больше не может вернуть 403.
    callback = make_callback("start_combat:5")
    api = AsyncMock()
    api.start_combat.side_effect = ApiError(403, "level_too_low")

    await start_combat(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once_with("Финальный босс пока недоступен на этом уровне.", show_alert=True)


async def test_start_combat_shows_fight_flee_and_auto_buttons():
    callback = make_callback("start_combat:5")
    api = AsyncMock()
    api.start_combat.return_value = {
        "combat_session_id": 5, "status": "awaiting_confirmation", "enemy_type": "wolf", "text": "..."
    }

    await start_combat(callback, api)

    api.start_combat.assert_awaited_once_with(1, 5)
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["confirm_fight:5", "confirm_flee:5", "confirm_fight_auto:5"]


async def test_start_combat_against_boss_hides_auto_and_flee_buttons():
    # docs/notes.md, пп.40/57 — ни автобоя (зельём в нём всё равно нельзя
    # пользоваться), ни "Отступить" (из боя с боссом нельзя сбежать) —
    # только "Вступить в бой", единственная кнопка.
    callback = make_callback("start_combat:5")
    api = AsyncMock()
    api.start_combat.return_value = {
        "combat_session_id": 5, "status": "awaiting_confirmation", "enemy_type": "boss", "text": "..."
    }

    await start_combat(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["confirm_fight:5"]


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


async def test_confirm_fight_shows_power_attack_button_next_to_attack():
    # docs/combat_mechanics.md §3a — доступен на любом ходу игрока, в любом
    # бою, сразу с первого хода, без каких-либо условий.
    callback = make_callback("confirm_fight:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "result": None, "current_turn": "player", "text": "⚔️ Ты вступаешь в бой!"
    }

    await confirm_fight(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    row = markup.inline_keyboard[0]
    assert row[1].text == "💥 Мощный удар"
    assert row[1].callback_data == "take_turn_power:5"


async def test_confirm_fight_no_power_attack_button_on_defend_turn():
    # На ходу противника показывается только "Защищаться" — мощный удар
    # доступен исключительно на ходу атаки игрока.
    callback = make_callback("confirm_fight:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "result": None, "current_turn": "enemy", "text": "..."
    }

    await confirm_fight(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["take_turn:5"]


async def test_take_turn_power_sends_power_attack_flag():
    callback = make_callback("take_turn_power:5")
    api = AsyncMock()
    api.take_turn.return_value = {"status": "active", "current_turn": "enemy", "text": "..."}

    await take_turn_power(callback, api)

    api.take_turn.assert_awaited_once_with(1, 5, power_attack=True)


async def test_take_turn_sends_no_power_attack_flag():
    callback = make_callback("take_turn:5")
    api = AsyncMock()
    api.take_turn.return_value = {"status": "active", "current_turn": "enemy", "text": "..."}

    await take_turn(callback, api)

    api.take_turn.assert_awaited_once_with(1, 5, power_attack=False)


async def test_confirm_fight_shows_no_potion_buttons_when_none_owned():
    callback = make_callback("confirm_fight:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "current_turn": "player", "text": "...",
        "potions_small": 0, "potions_large": 0, "potion_used_this_battle": False,
    }

    await confirm_fight(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert len(markup.inline_keyboard) == 1  # только кнопка хода, без второй строки


async def test_confirm_fight_shows_both_potion_buttons_when_both_owned():
    # docs/notes.md, п.33 — зелье кнопкой, только на ходу игрока, только в
    # ручном бою: обе кнопки видны сразу, если куплены оба размера.
    callback = make_callback("confirm_fight:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "current_turn": "player", "text": "...",
        "potions_small": 2, "potions_large": 1, "potion_used_this_battle": False,
    }

    await confirm_fight(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert len(markup.inline_keyboard) == 2
    potion_row = markup.inline_keyboard[1]
    callback_datas = [btn.callback_data for btn in potion_row]
    assert callback_datas == ["use_potion:5:small", "use_potion:5:large"]


async def test_confirm_fight_shows_only_owned_potion_size():
    callback = make_callback("confirm_fight:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "current_turn": "player", "text": "...",
        "potions_small": 0, "potions_large": 3, "potion_used_this_battle": False,
    }

    await confirm_fight(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "use_potion:5:small" not in callback_datas
    assert "use_potion:5:large" in callback_datas


async def test_confirm_fight_hides_potion_buttons_when_already_used_this_battle():
    callback = make_callback("confirm_fight:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "current_turn": "player", "text": "...",
        "potions_small": 2, "potions_large": 1, "potion_used_this_battle": True,
    }

    await confirm_fight(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert len(markup.inline_keyboard) == 1


async def test_take_turn_hides_potion_buttons_on_enemy_turn():
    # Зелье — только "на этапе атаки" игрока, не на ходу противника (тот же
    # инвентарь мог бы формально позволить, но кнопка не должна появляться).
    callback = make_callback("take_turn:5")
    api = AsyncMock()
    api.take_turn.return_value = {
        "status": "active", "current_turn": "enemy", "text": "...",
        "potions_small": 2, "potions_large": 1, "potion_used_this_battle": False,
    }

    await take_turn(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert len(markup.inline_keyboard) == 1
    assert markup.inline_keyboard[0][0].text == "🛡️ Защищаться"


async def test_use_potion_success_shows_updated_turn_button():
    callback = make_callback("use_potion:5:large")
    api = AsyncMock()
    api.use_potion.return_value = {
        "status": "active", "current_turn": "enemy", "text": "🧪 Большое зелье: +25 HP.",
        "potions_small": 0, "potions_large": 0, "potion_used_this_battle": True,
    }

    await use_potion(callback, api)

    api.use_potion.assert_awaited_once_with(1, 5, "large")
    text = callback.message.edit_text.call_args.args[0]
    assert text == "🧪 Большое зелье: +25 HP."
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].text == "🛡️ Защищаться"  # ход уже передан противнику
    assert len(markup.inline_keyboard) == 1  # лимит сгорел — кнопок зелья больше нет
    callback.answer.assert_awaited_once()


async def test_use_potion_already_used_shows_alert_without_editing_message():
    callback = make_callback("use_potion:5:small")
    api = AsyncMock()
    api.use_potion.side_effect = ApiError(400, "already_used")

    await use_potion(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once_with("Зелье в этом бою уже использовано.", show_alert=True)


async def test_use_potion_not_owned_shows_distinct_alert():
    callback = make_callback("use_potion:5:small")
    api = AsyncMock()
    api.use_potion.side_effect = ApiError(400, "not_owned")

    await use_potion(callback, api)

    callback.answer.assert_awaited_once_with("У тебя нет такого зелья.", show_alert=True)


async def test_confirm_fight_shows_defend_button_when_enemy_goes_first():
    callback = make_callback("confirm_fight:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "active", "result": None, "current_turn": "enemy", "text": "..."
    }

    await confirm_fight(callback, api)

    button = callback.message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "🛡️ Защищаться"


async def test_confirm_fight_auto_shows_only_the_final_result():
    # Автобой (docs/notes.md, п.34) — никакой анимации по ходам, один вызов
    # edit_text с итогом.
    callback = make_callback("confirm_fight_auto:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {"status": "active", "current_turn": "player", "text": "..."}
    api.take_turn.side_effect = [
        {"status": "active", "current_turn": "enemy", "text": "Ход 1"},
        {"status": "active", "current_turn": "player", "text": "Ход 2"},
        {"status": "finished", "result": "victory", "text": "Ты победил!"},
    ]

    await confirm_fight_auto(callback, api)

    api.confirm_combat.assert_awaited_once_with(1, 5, "fight")
    assert api.take_turn.await_count == 3
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


async def test_confirm_fight_auto_stops_at_flee_decision():
    callback = make_callback("confirm_fight_auto:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {"status": "active", "current_turn": "player", "text": "..."}
    api.take_turn.return_value = {
        "status": "awaiting_flee_decision", "current_turn": "player", "text": "⚠️ Шанс уйти живым!"
    }

    await confirm_fight_auto(callback, api)

    callback.message.edit_text.assert_awaited_once()
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    # "Биться дальше" ведёт на автовариант — бой шёл в автобою (docs/notes.md, п.34).
    assert callback_datas == ["flee_decision_flee:5", "flee_decision_continue_auto:5"]


async def test_flee_decision_continue_auto_resumes_silently_to_the_end():
    callback = make_callback("flee_decision_continue_auto:5")
    api = AsyncMock()
    api.flee_decision.return_value = {"status": "active", "current_turn": "enemy", "text": "..."}
    api.take_turn.return_value = {"status": "finished", "result": "victory", "text": "Ты победил!"}

    await flee_decision_continue_auto(callback, api)

    api.flee_decision.assert_awaited_once_with(1, 5, "continue")
    callback.answer.assert_awaited_once()

    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.call_args.args[0]
    assert text == "Ты победил!"


async def test_confirm_flee_shows_post_battle_buttons():
    callback = make_callback("confirm_flee:5")
    api = AsyncMock()
    api.confirm_combat.return_value = {
        "status": "finished", "result": "player_fled", "text": "🏃 Тебе удалось уйти."
    }

    await confirm_flee(callback, api)

    api.confirm_combat.assert_awaited_once_with(1, 5, "flee")
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "refresh_after_battle" in callback_datas
    assert "search_encounter" in callback_datas
    assert "open_allocation" in callback_datas
    assert "show_rules" in callback_datas
    assert "search_boss_encounter" in callback_datas  # docs/notes.md, пп.37, 58 — тоже на постбоевой клавиатуре


async def test_confirm_flee_not_allowed_shows_alert_without_editing_message():
    # docs/notes.md, п.57 — у бота этой кнопки для босса и так нет, но на
    # случай гонки/устаревшей клавиатуры сервер отвечает 400, а не 200.
    callback = make_callback("confirm_flee:5")
    api = AsyncMock()
    api.confirm_combat.side_effect = ApiError(400, "flee_not_allowed")

    await confirm_flee(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once_with("Из боя с этим противником нельзя отступить.", show_alert=True)


async def test_take_turn_active_shows_turn_button():
    callback = make_callback("take_turn:5")
    api = AsyncMock()
    api.take_turn.return_value = {"status": "active", "current_turn": "enemy", "text": "..."}

    await take_turn(callback, api)

    button = callback.message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.callback_data == "take_turn:5"
    assert button.text == "🛡️ Защищаться"


async def test_take_turn_finished_shows_post_battle_buttons():
    # docs/notes.md, п.58 — кнопка финального босса на постбоевом экране
    # всегда активна, независимо от уровня.
    callback = make_callback("take_turn:5")
    api = AsyncMock()
    api.take_turn.return_value = {"status": "finished", "result": "victory", "text": "⚔️ Ты победил!"}

    await take_turn(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == [
        "refresh_after_battle", "search_encounter", "open_allocation", "show_rules", "search_boss_encounter"
    ]


async def test_take_turn_boss_victory_shows_restart_button_only():
    # docs/notes.md, п.36/41 — победа над боссом заканчивает игру: вместо
    # обычной постбоевой клавиатуры единственная кнопка "Начать заново",
    # переиспользующая хендлер "reset_confirm:*" (bot/handlers/start.py) с
    # причиной "boss_victory" — для аналитики на сервере.
    callback = make_callback("take_turn:5")
    api = AsyncMock()
    api.take_turn.return_value = {
        "status": "finished", "result": "victory", "enemy_type": "boss", "text": "🎉 Ты повергнул Лесного Короля!"
    }

    await take_turn(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["reset_confirm:boss_victory"]


async def test_take_turn_boss_defeat_shows_normal_post_battle_buttons():
    # Поражение от босса — обычный постбоевой экран, можно попробовать снова.
    callback = make_callback("take_turn:5")
    api = AsyncMock()
    api.take_turn.return_value = {
        "status": "finished", "result": "defeat", "enemy_type": "boss", "text": "💀 Ты пал..."
    }

    await take_turn(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "search_encounter" in callback_datas
    assert "reset_confirm" not in callback_datas


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
    api.flee_decision.return_value = {
        "status": "finished", "result": "defeat", "text": "💀 Ты пал..."
    }

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
    api.get_character.return_value = {"hp_current": 15.0, "hp_max": 50.0, "hp_seconds_to_full": 35.0, "level": 3}

    await refresh_after_battle(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert text == "❤️ HP: 15/50\n⏳ Полное восстановление через: ~35 сек."
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "show_rules" in callback_datas  # экран "Обновить" тоже должен вести к правилам


async def test_refresh_after_battle_omits_timer_when_hp_full():
    callback = make_callback("refresh_after_battle")
    api = AsyncMock()
    api.get_character.return_value = {"hp_current": 50.0, "hp_max": 50.0, "hp_seconds_to_full": 0, "level": 3}

    await refresh_after_battle(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert text == "❤️ HP: 50/50"


async def test_build_resume_keyboard_awaiting_initiative():
    resume = {"status": "awaiting_initiative", "enemy_type": "wolf"}
    markup = build_resume_keyboard(5, resume)
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["start_combat:5"]


async def test_build_resume_keyboard_awaiting_confirmation_shows_auto_button():
    resume = {"status": "awaiting_confirmation", "enemy_type": "wolf"}
    markup = build_resume_keyboard(5, resume)
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["confirm_fight:5", "confirm_flee:5", "confirm_fight_auto:5"]


async def test_build_resume_keyboard_awaiting_confirmation_hides_auto_and_flee_buttons_for_boss():
    resume = {"status": "awaiting_confirmation", "enemy_type": "boss"}
    markup = build_resume_keyboard(5, resume)
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["confirm_fight:5"]


async def test_build_resume_keyboard_active_shows_turn_and_potion_buttons():
    resume = {
        "status": "active", "current_turn": "player", "enemy_type": "wolf",
        "potions_small": 1, "potions_large": 0, "potion_used_this_battle": False,
    }
    markup = build_resume_keyboard(5, resume)
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["take_turn:5", "take_turn_power:5", "use_potion:5:small"]


async def test_build_resume_keyboard_awaiting_flee_decision():
    resume = {"status": "awaiting_flee_decision", "enemy_type": "wolf"}
    markup = build_resume_keyboard(5, resume)
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["flee_decision_flee:5", "flee_decision_continue:5"]


async def test_build_resume_keyboard_awaiting_initiative_boss_shows_challenge_and_back():
    # docs/notes.md, п.51 — восстановленный экран с боссом до инициативы
    # выглядит так же, как и свежий: запас зелий + "Назад" вместо обычной
    # "Определить инициативу".
    resume = {"status": "awaiting_initiative", "enemy_type": "boss"}
    markup = build_resume_keyboard(5, resume)
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callback_datas == ["start_combat:5", "cancel_encounter:5"]


async def test_build_resume_text_appends_potion_stock_for_boss_awaiting_initiative():
    resume = {
        "status": "awaiting_initiative", "enemy_type": "boss", "text": "Ты входишь в чертог Лесного Короля.",
        "potions_small": 3, "potions_large": 0,
    }
    text = build_resume_text(resume)
    assert text == (
        "Ты входишь в чертог Лесного Короля.\n\n"
        "🧪 Твой запас:\n"
        "  Малое: 3/5\n"
        "  Большое: 0/3"
    )


async def test_build_resume_text_unchanged_for_non_boss_awaiting_initiative():
    resume = {"status": "awaiting_initiative", "enemy_type": "wolf", "text": "Ты наткнулся на волка."}
    assert build_resume_text(resume) == "Ты наткнулся на волка."


async def test_cancel_encounter_returns_to_stats_screen():
    callback = make_callback("cancel_encounter:9")
    api = AsyncMock()
    api.get_character.return_value = {
        "nickname": "Hero", "level": 3, "hp_current": 40.0, "hp_max": 60.0,
        "strength": 5, "agility": 3, "luck": 2, "victory_points": 15, "points_to_next_level": 5,
    }

    await cancel_encounter(callback, api)

    api.cancel_combat_session.assert_awaited_once_with(1, 9)
    text = callback.message.edit_text.call_args.args[0]
    assert "Hero" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "search_encounter" in callback_datas
    callback.answer.assert_awaited_once()


async def test_cancel_encounter_shows_alert_when_already_started():
    callback = make_callback("cancel_encounter:9")
    api = AsyncMock()
    api.cancel_combat_session.side_effect = ApiError(409, "unexpected session status: 'active'")

    await cancel_encounter(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once_with("Бой уже начался — отменить нельзя.", show_alert=True)
