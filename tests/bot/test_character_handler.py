"""Тесты bot/handlers/character.py — экран статов и прокачка."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.client import ApiError
from bot.handlers.character import (
    allocate_creation,
    allocate_levelup,
    back_to_stats,
    finish_creation,
    open_allocation,
)

pytestmark = pytest.mark.asyncio

BASE_CHARACTER = {
    "id": 1, "nickname": "Hero", "level": 1, "victory_points": 0, "points_to_next_level": 8,
    "unspent_stat_points": 5, "strength": 3, "agility": 3, "luck": 1, "vitality": 3,
    "hp_current": 50.0, "hp_max": 50.0,
}


def make_callback(data: str, user_id: int = 1) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def test_open_allocation_shows_levelup_screen():
    callback = make_callback("open_allocation")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER

    await open_allocation(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "Прокачка характеристик" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[-1][0].callback_data == "back_to_stats"


async def test_back_to_stats_shows_stats_screen():
    callback = make_callback("back_to_stats")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER

    await back_to_stats(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "Hero" in text
    assert "Уровень" in text


async def test_allocate_levelup_spends_point_and_refreshes_screen():
    callback = make_callback("allocate:strength")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER
    api.allocate_point.return_value = {
        "character": {**BASE_CHARACTER, "strength": 4, "unspent_stat_points": 4}
    }

    await allocate_levelup(callback, api)

    api.allocate_point.assert_awaited_once_with(1, "strength")
    text = callback.message.edit_text.call_args.args[0]
    assert "Сила: 4" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[-1][0].callback_data == "back_to_stats"


async def test_allocate_levelup_no_points_shows_alert_without_editing_message():
    callback = make_callback("allocate:strength")
    api = AsyncMock()
    api.get_character.return_value = {**BASE_CHARACTER, "unspent_stat_points": 0}
    api.allocate_point.side_effect = ApiError(400, "no unspent stat points available")

    await allocate_levelup(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once()
    assert callback.answer.call_args.kwargs.get("show_alert") is True


async def test_allocate_creation_uses_creation_screen():
    callback = make_callback("create_allocate:vitality")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER
    api.allocate_point.return_value = {
        "character": {**BASE_CHARACTER, "vitality": 4, "unspent_stat_points": 4, "hp_max": 60.0}
    }

    await allocate_creation(callback, api)

    api.allocate_point.assert_awaited_once_with(1, "vitality")
    text = callback.message.edit_text.call_args.args[0]
    assert "Создание героя" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[-1][0].callback_data == "finish_creation"


async def test_finish_creation_shows_stats_screen_with_search_button():
    callback = make_callback("finish_creation")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER

    await finish_creation(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "Hero" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "search_encounter"
