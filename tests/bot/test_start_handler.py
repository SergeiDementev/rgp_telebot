"""Тесты bot/handlers/start.py — Message/CallbackQuery подменены MagicMock."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.client import ApiError
from bot.handlers.start import (
    RESET_CONFIRM_TEXT,
    RESUME_BATTLE_PREFIX,
    WELCOME_TEXT,
    cmd_reset,
    cmd_start,
    reset_confirm,
    reset_request,
    start_game,
)
from core import i18n

pytestmark = pytest.mark.asyncio


def make_message(user_id: int = 1) -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
    message.answer = AsyncMock()
    return message


def make_callback(user_id: int = 1, full_name: str = "Hero", language_code: str = "ru") -> MagicMock:
    callback = MagicMock()
    callback.from_user.id = user_id
    callback.from_user.full_name = full_name
    callback.from_user.language_code = language_code
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def test_cmd_start_new_user_shows_welcome_with_start_button():
    message = make_message()
    api = AsyncMock()
    api.get_character.side_effect = ApiError(404, "not found")

    await cmd_start(message, api)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert args[0] == WELCOME_TEXT
    assert kwargs["reply_markup"] is not None


async def test_cmd_start_existing_user_shows_welcome_then_stats():
    message = make_message()
    api = AsyncMock()
    api.get_character.return_value = {
        "nickname": "Hero", "level": 2, "hp_current": 40.0, "hp_max": 60.0,
        "strength": 5, "agility": 3, "luck": 2, "victory_points": 15, "points_to_next_level": 5,
    }

    await cmd_start(message, api)

    assert message.answer.await_count == 2
    first_call, second_call = message.answer.call_args_list
    assert first_call.args[0] == WELCOME_TEXT
    assert "Hero" in second_call.args[0]


async def test_cmd_start_resumes_active_battle_instead_of_stats_screen():
    # docs/notes.md, п.48 — незавершённый бой не теряется, если сообщение с
    # его клавиатурой пропало (например, чат в Telegram был удалён):
    # CombatSession в БД остаётся активной, /start восстанавливает экран боя.
    message = make_message()
    api = AsyncMock()
    api.get_character.return_value = {"nickname": "Hero", "active_combat_session_id": 5}
    api.resume_combat_session.return_value = {
        "status": "active", "current_turn": "player", "enemy_type": "wolf", "text": "❤️ Ты: 34/50   👹 Волк: 12/50",
        "potions_small": 0, "potions_large": 0, "potion_used_this_battle": False,
    }

    await cmd_start(message, api)

    api.resume_combat_session.assert_awaited_once_with(message.from_user.id, 5)
    # Баннер всё ещё шлётся первым сообщением, как и при обычном /start —
    # только вторым сообщением идёт восстановленный бой, а не меню персонажа.
    assert message.answer.await_count == 2
    first_call, second_call = message.answer.call_args_list
    assert first_call.args[0] == WELCOME_TEXT
    args, kwargs = second_call
    assert args[0] == f"{RESUME_BATTLE_PREFIX}❤️ Ты: 34/50   👹 Волк: 12/50"
    callback_datas = [btn.callback_data for row in kwargs["reply_markup"].inline_keyboard for btn in row]
    assert callback_datas == ["take_turn:5", "take_turn_power:5"]


async def test_cmd_start_reraises_non_404_errors():
    message = make_message()
    api = AsyncMock()
    api.get_character.side_effect = ApiError(500, "boom")

    with pytest.raises(ApiError):
        await cmd_start(message, api)


async def test_start_game_creates_character_when_missing():
    callback = make_callback(full_name="Hero", language_code="ru")
    api = AsyncMock()
    api.get_character.side_effect = ApiError(404, "not found")
    api.create_character.return_value = {
        "id": 1, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await start_game(callback, api)

    api.create_character.assert_awaited_once_with(callback.from_user.id, "Hero", "ru")
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.call_args.args[0]
    assert "Создание героя" in text
    callback.answer.assert_awaited_once()


async def test_start_game_detects_english_from_language_code():
    # docs/notes.md — language_code, не начинающийся с "ru" (в том числе
    # отсутствующий), -> "en" по умолчанию для нового персонажа.
    callback = make_callback(full_name="Hero", language_code="en-US")
    api = AsyncMock()
    api.get_character.side_effect = ApiError(404, "not found")
    api.create_character.return_value = {
        "id": 1, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await start_game(callback, api)

    api.create_character.assert_awaited_once_with(callback.from_user.id, "Hero", "en")


async def test_start_game_reuses_existing_character_without_recreating():
    callback = make_callback()
    api = AsyncMock()
    api.get_character.return_value = {
        "id": 1, "nickname": "Hero", "level": 1, "unspent_stat_points": 2, "strength": 4,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 3,
    }

    await start_game(callback, api)

    api.create_character.assert_not_called()
    callback.message.edit_text.assert_awaited_once()


async def test_cmd_reset_asks_for_confirmation():
    message = make_message()

    await cmd_reset(message)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert args[0] == RESET_CONFIRM_TEXT
    markup = kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "reset_confirm:manual_reset" in callback_datas
    # "Отмена" ведёт на главный экран персонажа (docs/notes.md), не в
    # тупиковое сообщение без кнопок.
    assert "back_to_stats" in callback_datas


async def test_reset_request_edits_message_with_confirmation():
    # Кнопка "🗑 Обнулить персонажа" на экране прокачки (bot/handlers/
    # character.py, mode="levelup") — то же подтверждение, что и /reset, но
    # редактирует сообщение, а не шлёт новое.
    callback = make_callback()

    await reset_request(callback)

    callback.message.edit_text.assert_awaited_once()
    args, kwargs = callback.message.edit_text.call_args
    assert args[0] == RESET_CONFIRM_TEXT
    markup = kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "reset_confirm:manual_reset" in callback_datas
    assert "back_to_stats" in callback_datas
    callback.answer.assert_awaited_once()


async def test_reset_confirm_deletes_character_and_shows_creation_screen():
    # Без приветственного текста и без лишнего клика "Начать игру" — сразу
    # экран создания героя (docs/notes.md).
    callback = make_callback(full_name="Hero")
    callback.data = "reset_confirm:manual_reset"
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "nickname": "Hero", "language": "ru"}
    api.create_character.return_value = {
        "id": 1, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await reset_confirm(callback, api)

    api.delete_character.assert_awaited_once_with(callback.from_user.id, reason="manual_reset")
    api.create_character.assert_awaited_once_with(callback.from_user.id, "Hero", "ru")
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.call_args.args[0]
    assert "Создание героя" in text
    assert WELCOME_TEXT not in text
    callback.answer.assert_awaited_once()


async def test_reset_confirm_carries_over_existing_language_choice():
    # docs/notes.md — язык переносится со старого персонажа, а не
    # переопределяется заново по language_code профиля: явный выбор через
    # /language не должен тихо сбрасываться обнулением персонажа.
    callback = make_callback(full_name="Hero", language_code="ru")
    callback.data = "reset_confirm:manual_reset"
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "nickname": "Hero", "language": "en"}
    api.create_character.return_value = {
        "id": 1, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await reset_confirm(callback, api)

    api.create_character.assert_awaited_once_with(callback.from_user.id, "Hero", "en")


async def test_cmd_start_shows_stats_in_character_language():
    # docs/notes.md, блок 3 — cmd_start сам выставляет локаль (не проходит
    # через bot/utils.py::get_character_or_prompt_start, у него свой прямой
    # api.get_character()), прежде чем звать render_stats_screen.
    message = make_message()
    api = AsyncMock()
    api.get_character.return_value = {
        "nickname": "Hero", "level": 2, "hp_current": 40.0, "hp_max": 60.0,
        "strength": 5, "agility": 3, "luck": 2, "victory_points": 15, "points_to_next_level": 5,
        "language": "en",
    }
    try:
        await cmd_start(message, api)
        second_call = message.answer.call_args_list[1]
        assert "🏅 Level: 2" in second_call.args[0]
        assert "💪 Strength: 5" in second_call.args[0]
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)


async def test_start_game_renders_creation_screen_in_character_language():
    callback = make_callback(full_name="Hero", language_code="en-US")
    api = AsyncMock()
    api.get_character.side_effect = ApiError(404, "not found")
    api.create_character.return_value = {
        "id": 1, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
        "language": "en",
    }
    try:
        await start_game(callback, api)
        text = callback.message.edit_text.call_args.args[0]
        assert "🧙 Hero Creation" in text
        assert "💪 Strength: 3" in text
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)


async def test_reset_confirm_renders_creation_screen_in_carried_over_language():
    callback = make_callback(full_name="Hero")
    callback.data = "reset_confirm:manual_reset"
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "nickname": "Hero", "language": "en"}
    api.create_character.return_value = {
        "id": 1, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
        "language": "en",
    }
    try:
        await reset_confirm(callback, api)
        text = callback.message.edit_text.call_args.args[0]
        assert "🧙 Hero Creation" in text
    finally:
        i18n.set_locale(i18n.DEFAULT_LOCALE)


async def test_reset_confirm_passes_boss_victory_reason():
    # docs/notes.md, п.41 — тот же хендлер, что и обычный сброс, но с другой
    # причиной в callback_data: экран поздравления после победы над боссом
    # (bot/handlers/combat.py::_boss_victory_keyboard) ведёт сюда с
    # "reset_confirm:boss_victory", не "manual_reset".
    callback = make_callback(full_name="Hero")
    callback.data = "reset_confirm:boss_victory"
    api = AsyncMock()
    api.get_character.return_value = {"id": 2, "nickname": "Hero", "language": "ru"}
    api.create_character.return_value = {
        "id": 2, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await reset_confirm(callback, api)

    api.delete_character.assert_awaited_once_with(callback.from_user.id, reason="boss_victory")
