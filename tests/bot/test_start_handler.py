"""Тесты bot/handlers/start.py — Message/CallbackQuery подменены MagicMock."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.client import ApiError
from bot.handlers.start import (
    cmd_reset,
    cmd_start,
    reset_confirm,
    reset_confirm_text,
    reset_request,
    resume_battle_prefix,
    start_game,
    welcome_text,
)
from core import i18n

pytestmark = pytest.mark.asyncio


def make_message(user_id: int = 1) -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
    message.chat.id = user_id
    message.answer = AsyncMock()
    message.bot.delete_message = AsyncMock()
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
    assert args[0] == welcome_text()
    assert kwargs["reply_markup"] is not None


async def test_cmd_start_existing_user_shows_welcome_then_stats():
    message = make_message()
    api = AsyncMock()
    api.get_character.return_value = {
        "id": 1, "nickname": "Hero", "level": 2, "hp_current": 40.0, "hp_max": 60.0,
        "strength": 5, "agility": 3, "luck": 2, "victory_points": 15, "points_to_next_level": 5,
    }

    await cmd_start(message, api)

    assert message.answer.await_count == 2
    first_call, second_call = message.answer.call_args_list
    assert first_call.args[0] == welcome_text()
    assert "Hero" in second_call.args[0]


async def test_cmd_start_resumes_active_battle_instead_of_stats_screen():
    # docs/notes.md, п.48 — незавершённый бой не теряется, если сообщение с
    # его клавиатурой пропало (например, чат в Telegram был удалён):
    # CombatSession в БД остаётся активной, /start восстанавливает экран боя.
    message = make_message()
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "nickname": "Hero", "active_combat_session_id": 5}
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
    assert first_call.args[0] == welcome_text()
    args, kwargs = second_call
    assert args[0] == f"{resume_battle_prefix()}❤️ Ты: 34/50   👹 Волк: 12/50"
    callback_datas = [btn.callback_data for row in kwargs["reply_markup"].inline_keyboard for btn in row]
    assert callback_datas == ["take_turn:5", "take_turn_power:5"]


async def test_cmd_start_reraises_non_404_errors():
    message = make_message()
    api = AsyncMock()
    api.get_character.side_effect = ApiError(500, "boom")

    with pytest.raises(ApiError):
        await cmd_start(message, api)


_STATS_FIELDS = {
    "nickname": "Hero", "level": 2, "hp_current": 40.0, "hp_max": 60.0,
    "strength": 5, "agility": 3, "luck": 2, "victory_points": 15, "points_to_next_level": 5,
}


async def test_cmd_start_deletes_old_messages_after_sending_new_ones():
    # docs/notes.md — повторный /start удаляет оба старых постоянных
    # сообщения вместо накопления истории чата. Порядок — отправить и
    # сохранить в БД id новых сообщений, ПОТОМ удалить старые (ревизия
    # двуязычности: не наоборот, см. test_cmd_start_leaves_old_messages_
    # and_db_untouched_when_send_fails ниже — какой сценарий это решает).
    message = make_message()
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, **_STATS_FIELDS, "welcome_message_id": 10, "main_message_id": 20}

    await cmd_start(message, api)

    assert message.bot.delete_message.await_count == 2
    deleted_ids = {call.args[1] for call in message.bot.delete_message.call_args_list}
    assert deleted_ids == {10, 20}
    api.set_message_ids.assert_awaited_once()


async def test_cmd_start_concurrent_calls_are_serialized_and_use_fresh_state():
    # docs/notes.md — ревизия двуязычности: двойной быстрый /start без
    # лока — обе гонки читают одни и те же старые id (10/20), шлют 4
    # сообщения вместо 2, и каждая гонка пытается удалить исходные 10/20 —
    # первая пара НОВЫХ сообщений (сохранённая первой гонкой) никогда не
    # удаляется, остаётся висеть в чате. С локом на пользователя
    # (bot/utils.py::user_lock) вторая гонка ждёт первую и перечитывает
    # состояние заново — значит удаляет уже id, сохранённые ПЕРВОЙ гонкой,
    # а не исходные 10/20 дважды.
    state = {"welcome_message_id": 10, "main_message_id": 20}
    next_message_id = iter(range(100, 200))
    sent_message_ids = []
    deleted_ids = []
    message = make_message()

    async def fake_get_character(_user_id):
        await asyncio.sleep(0)
        return {"id": 1, **_STATS_FIELDS, **state}

    async def fake_answer(*_args, **_kwargs):
        await asyncio.sleep(0)
        message_id = next(next_message_id)
        sent_message_ids.append(message_id)
        return MagicMock(message_id=message_id)

    async def fake_set_message_ids(_character_id, **kwargs):
        await asyncio.sleep(0)
        state.update({key: value for key, value in kwargs.items() if value is not None})

    async def fake_delete_message(_chat_id, message_id):
        await asyncio.sleep(0)
        deleted_ids.append(message_id)

    api = AsyncMock()
    api.get_character.side_effect = fake_get_character
    api.set_message_ids.side_effect = fake_set_message_ids
    message.answer.side_effect = fake_answer
    message.bot.delete_message.side_effect = fake_delete_message

    await asyncio.gather(cmd_start(message, api), cmd_start(message, api))

    assert message.answer.await_count == 4
    assert message.bot.delete_message.await_count == 4
    # 10/20 удалены ровно по разу (первой гонкой) — без сериализации обе
    # гонки прочитали бы одни и те же 10/20 и удалили бы их по два раза.
    assert deleted_ids.count(10) == 1
    assert deleted_ids.count(20) == 1
    # Финальное состояние в "БД" — id именно ВТОРОЙ (последней) пары
    # сообщений, обе из которых реально были отправлены.
    assert state["welcome_message_id"] in sent_message_ids
    assert state["main_message_id"] in sent_message_ids


async def test_cmd_start_skips_deletion_when_no_saved_message_ids():
    # Первый /start после раскатки этого поля, или совсем новый персонаж —
    # welcome_message_id/main_message_id ещё None, нечего удалять.
    message = make_message()
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, **_STATS_FIELDS}

    await cmd_start(message, api)

    message.bot.delete_message.assert_not_called()


async def test_cmd_start_deletion_failure_does_not_prevent_new_messages():
    # docs/notes.md — ошибки удаления (сообщение уже недоступно, чат другой
    # и т.п.) не приводят к падению, просто пропускаем этот шаг.
    message = make_message()
    message.bot.delete_message.side_effect = TelegramBadRequest(
        method=MagicMock(), message="message to delete not found"
    )
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, **_STATS_FIELDS, "welcome_message_id": 10, "main_message_id": 20}

    await cmd_start(message, api)  # не должно бросить исключение

    assert message.answer.await_count == 2
    api.set_message_ids.assert_awaited_once()


async def test_cmd_start_leaves_old_messages_and_db_untouched_when_send_fails():
    # docs/notes.md — ревизия двуязычности: если отправка НОВОГО сообщения
    # рвётся сетевым сбоем (не TelegramBadRequest — та бизнес-ошибка не
    # такая; здесь любая Exception), старые сообщения не должны удаляться,
    # а БД не должна переписываться на id несуществующих сообщений. Порядок
    # "отправить+сохранить, потом удалить" гарантирует это без отдельного
    # отката: раз отправка не удалась, до удаления/сохранения просто не
    # доходит.
    message = make_message()
    message.answer.side_effect = [RuntimeError("connection reset"), AsyncMock()]
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, **_STATS_FIELDS, "welcome_message_id": 10, "main_message_id": 20}

    with pytest.raises(RuntimeError):
        await cmd_start(message, api)

    message.bot.delete_message.assert_not_called()
    api.set_message_ids.assert_not_called()


async def test_cmd_start_notifies_user_best_effort_when_send_fails():
    message = make_message()
    message.answer.side_effect = [RuntimeError("connection reset"), AsyncMock()]
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, **_STATS_FIELDS}

    with pytest.raises(RuntimeError):
        await cmd_start(message, api)

    # 1-я попытка (welcome) падает, 2-я вызов message.answer — уже сама
    # best-effort попытка уведомить об ошибке (не вторая часть исходной
    # пары welcome/main — до неё дело не доходит).
    assert message.answer.await_count == 2
    second_call = message.answer.call_args_list[1]
    assert second_call.args[0] == i18n.t("start.error.send_failed")


async def test_cmd_start_second_send_failure_does_not_mask_first_error():
    # Если даже best-effort уведомление тоже не проходит — не маскируем
    # исходную ошибку своей собственной.
    message = make_message()
    message.answer.side_effect = RuntimeError("connection reset")
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, **_STATS_FIELDS}

    with pytest.raises(RuntimeError):
        await cmd_start(message, api)


async def test_cmd_start_saves_new_message_ids_after_sending():
    message = make_message()
    message.answer.side_effect = [MagicMock(message_id=100), MagicMock(message_id=200)]
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, **_STATS_FIELDS}

    await cmd_start(message, api)

    api.set_message_ids.assert_awaited_once_with(1, welcome_message_id=100, main_message_id=200)


async def test_cmd_start_saves_message_ids_for_resume_branch_too():
    message = make_message()
    message.answer.side_effect = [MagicMock(message_id=100), MagicMock(message_id=200)]
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "nickname": "Hero", "active_combat_session_id": 5}
    api.resume_combat_session.return_value = {
        "status": "active", "current_turn": "player", "enemy_type": "wolf", "text": "...",
        "potions_small": 0, "potions_large": 0, "potion_used_this_battle": False,
    }

    await cmd_start(message, api)

    api.set_message_ids.assert_awaited_once_with(1, welcome_message_id=100, main_message_id=200)


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
    assert args[0] == reset_confirm_text()
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
    assert args[0] == reset_confirm_text()
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
    assert welcome_text() not in text
    callback.answer.assert_awaited_once()


async def test_reset_confirm_saves_main_message_id_for_new_character():
    # docs/notes.md — новая строка персонажа (старая архивирована), первое
    # закрепление main_message_id за ней. welcome_message_id не трогаем —
    # отдельного приветственного сообщения в этом флоу нет.
    callback = make_callback(full_name="Hero")
    callback.data = "reset_confirm:manual_reset"
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "nickname": "Hero", "language": "ru"}
    api.create_character.return_value = {
        "id": 2, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await reset_confirm(callback, api)

    api.set_message_ids.assert_awaited_once_with(2, main_message_id=callback.message.message_id)


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


async def test_reset_confirm_deletes_orphaned_previous_main_message():
    # docs/notes.md, №86 закрыт — подтверждение через /reset-команду
    # (cmd_reset шлёт отдельное сообщение с подтверждением, не по
    # сохранённому main_message_id, в отличие от кнопки "🗑 Обнулить
    # персонажа"/reset_request, которая редактирует то же main-сообщение).
    # Раньше прежнее main-сообщение (id=20) в этом случае просто теряло
    # свой id из БД (перезаписан на id ЭТОГО, другого сообщения) и
    # оставалось сиротой в чате навсегда.
    callback = make_callback(full_name="Hero")
    callback.data = "reset_confirm:manual_reset"
    callback.message.message_id = 999  # id сообщения-подтверждения от /reset, не main
    callback.message.chat.id = 1
    callback.bot.delete_message = AsyncMock()
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "nickname": "Hero", "language": "ru", "main_message_id": 20}
    api.create_character.return_value = {
        "id": 2, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await reset_confirm(callback, api)

    callback.bot.delete_message.assert_awaited_once_with(1, 20)


async def test_reset_confirm_does_not_delete_when_confirmation_is_the_main_message():
    # Путь через кнопку "🗑 Обнулить персонажа" — reset_request отредактировал
    # ТО ЖЕ main-сообщение (bot/handlers/start.py::reset_request), значит
    # old main_message_id уже равен callback.message.message_id: удалять
    # нечего, это не сирота.
    callback = make_callback(full_name="Hero")
    callback.data = "reset_confirm:manual_reset"
    callback.message.message_id = 20
    callback.message.chat.id = 1
    callback.bot.delete_message = AsyncMock()
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "nickname": "Hero", "language": "ru", "main_message_id": 20}
    api.create_character.return_value = {
        "id": 2, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await reset_confirm(callback, api)

    callback.bot.delete_message.assert_not_called()


async def test_reset_confirm_skips_deletion_when_no_previous_main_message():
    # Первый /reset после раскатки этого поля, или персонаж ещё ни разу не
    # проходил /start — main_message_id ещё None, нечего удалять.
    callback = make_callback(full_name="Hero")
    callback.data = "reset_confirm:manual_reset"
    callback.message.message_id = 999
    callback.message.chat.id = 1
    callback.bot.delete_message = AsyncMock()
    api = AsyncMock()
    api.get_character.return_value = {"id": 1, "nickname": "Hero", "language": "ru"}
    api.create_character.return_value = {
        "id": 2, "nickname": "Hero", "level": 1, "unspent_stat_points": 5, "strength": 3,
        "agility": 3, "luck": 1, "vitality": 3, "hp_max": 50.0, "points_to_next_level": 8,
    }

    await reset_confirm(callback, api)

    callback.bot.delete_message.assert_not_called()


async def test_cmd_start_shows_stats_in_character_language():
    # docs/notes.md, блок 3 — cmd_start сам выставляет локаль (не проходит
    # через bot/utils.py::get_character_or_prompt_start, у него свой прямой
    # api.get_character()), прежде чем звать render_stats_screen.
    message = make_message()
    api = AsyncMock()
    api.get_character.return_value = {
        "id": 1, "nickname": "Hero", "level": 2, "hp_current": 40.0, "hp_max": 60.0,
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
