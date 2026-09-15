"""Тесты bot/handlers/start.py — Message/CallbackQuery подменены MagicMock."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.client import ApiError
from bot.handlers.start import (
    RESET_CONFIRM_TEXT,
    WELCOME_TEXT,
    cmd_reset,
    cmd_start,
    reset_cancel,
    reset_confirm,
    reset_request,
    start_game,
)

pytestmark = pytest.mark.asyncio


def make_message(user_id: int = 1) -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
    message.answer = AsyncMock()
    return message


def make_callback(user_id: int = 1, full_name: str = "Hero") -> MagicMock:
    callback = MagicMock()
    callback.from_user.id = user_id
    callback.from_user.full_name = full_name
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


async def test_cmd_start_reraises_non_404_errors():
    message = make_message()
    api = AsyncMock()
    api.get_character.side_effect = ApiError(500, "boom")

    with pytest.raises(ApiError):
        await cmd_start(message, api)


async def test_start_game_creates_character_when_missing():
    callback = make_callback(full_name="Hero")
    api = AsyncMock()
    api.get_character.side_effect = ApiError(404, "not found")
    api.create_character.return_value = {
        "id": 1, "nickname": "Hero", "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await start_game(callback, api)

    api.create_character.assert_awaited_once_with(callback.from_user.id, "Hero")
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.call_args.args[0]
    assert "Создание героя" in text
    callback.answer.assert_awaited_once()


async def test_start_game_reuses_existing_character_without_recreating():
    callback = make_callback()
    api = AsyncMock()
    api.get_character.return_value = {
        "id": 1, "nickname": "Hero", "unspent_stat_points": 2, "strength": 4,
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
    assert "reset_confirm" in callback_datas
    assert "reset_cancel" in callback_datas


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
    assert "reset_confirm" in callback_datas
    assert "reset_cancel" in callback_datas
    callback.answer.assert_awaited_once()


async def test_reset_confirm_deletes_character_and_shows_start_button():
    callback = make_callback()
    api = AsyncMock()

    await reset_confirm(callback, api)

    api.delete_character.assert_awaited_once_with(callback.from_user.id)
    callback.message.edit_text.assert_awaited_once()
    args, kwargs = callback.message.edit_text.call_args
    assert args[0] == WELCOME_TEXT
    assert kwargs["reply_markup"] is not None
    callback.answer.assert_awaited_once()


async def test_reset_cancel_does_not_touch_character():
    callback = make_callback()

    await reset_cancel(callback)

    callback.message.edit_text.assert_awaited_once_with("Отменено.")
    callback.answer.assert_awaited_once()
