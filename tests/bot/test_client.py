"""Тесты bot/client.py — сборка запросов и разбор ответов, без реального API."""

import json

import httpx
import pytest

from bot.client import ApiClient, ApiError

pytestmark = pytest.mark.asyncio


def make_client(handler) -> ApiClient:
    transport = httpx.MockTransport(handler)
    return ApiClient(transport=transport)


def _echo_handler(status_code: int = 200, body: dict | None = None):
    """Хендлер, который просто запоминает запрос и возвращает заданный ответ."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["json"] = json.loads(request.content) if request.content else None
        return httpx.Response(status_code, json=body if body is not None else {})

    return handler, captured


async def test_create_character_sends_correct_request_without_telegram_header():
    handler, captured = _echo_handler(201, {"id": 1, "telegram_user_id": 1, "nickname": "Hero"})
    client = make_client(handler)

    result = await client.create_character(1, "Hero")

    assert captured["method"] == "POST"
    assert captured["path"] == "/character"
    assert captured["json"] == {"telegram_user_id": 1, "nickname": "Hero", "language": "ru"}
    assert captured["headers"]["x-internal-api-key"] == "dev-local-key"
    assert "x-telegram-user-id" not in captured["headers"]
    assert result["nickname"] == "Hero"


async def test_get_character_uses_path_param():
    handler, captured = _echo_handler(200, {"id": 1, "telegram_user_id": 42})
    client = make_client(handler)

    await client.get_character(42)

    assert captured["method"] == "GET"
    assert captured["path"] == "/character/42"


async def test_allocate_point_sends_stat_in_body():
    handler, captured = _echo_handler(200, {"character": {"strength": 4}})
    client = make_client(handler)

    result = await client.allocate_point(1, "strength")

    assert captured["path"] == "/character/1/allocate_point"
    assert captured["json"] == {"stat": "strength"}
    assert result["character"]["strength"] == 4


async def test_sell_loot_posts_to_correct_path():
    handler, captured = _echo_handler(200, {"character": {"gold": 30, "loot": {}}})
    client = make_client(handler)

    result = await client.sell_loot(1)

    assert captured["method"] == "POST"
    assert captured["path"] == "/character/1/sell_loot"
    assert captured["json"] is None
    assert result["character"]["gold"] == 30


async def test_buy_potion_sends_size_in_body():
    handler, captured = _echo_handler(200, {"character": {"potions_small": 1}})
    client = make_client(handler)

    result = await client.buy_potion(1, "small")

    assert captured["path"] == "/character/1/buy_potion"
    assert captured["json"] == {"size": "small"}
    assert result["character"]["potions_small"] == 1


async def test_set_language_sends_language_in_body():
    handler, captured = _echo_handler(200, {"character": {"language": "en"}})
    client = make_client(handler)

    result = await client.set_language(1, "en")

    assert captured["path"] == "/character/1/set_language"
    assert captured["json"] == {"language": "en"}
    assert result["character"]["language"] == "en"


async def test_set_message_ids_sends_both_ids_in_body():
    handler, captured = _echo_handler(200, {"character": {"welcome_message_id": 111, "main_message_id": 222}})
    client = make_client(handler)

    result = await client.set_message_ids(1, welcome_message_id=111, main_message_id=222)

    assert captured["path"] == "/character/1/set_message_ids"
    assert captured["json"] == {"welcome_message_id": 111, "main_message_id": 222}
    assert result["character"]["main_message_id"] == 222


async def test_set_message_ids_omits_unset_field_from_body():
    # docs/notes.md — частичное обновление: bot/handlers/character.py::
    # toggle_language передаёт только main_message_id.
    handler, captured = _echo_handler(200, {"character": {"main_message_id": 333}})
    client = make_client(handler)

    await client.set_message_ids(1, main_message_id=333)

    assert captured["json"] == {"main_message_id": 333}


async def test_delete_character_handles_204_no_content():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(204)  # без тела вообще — как реально шлёт FastAPI на 204

    client = make_client(handler)

    result = await client.delete_character(1, reason="manual_reset")

    assert captured["method"] == "DELETE"
    assert captured["params"] == {"reason": "manual_reset"}  # docs/notes.md, п.41 — для аналитики на сервере
    assert captured["path"] == "/character/1"
    assert result is None


async def test_search_encounter_sends_telegram_header():
    handler, captured = _echo_handler(200, {"combat_session_id": 5, "enemy_type": "wolf"})
    client = make_client(handler)

    result = await client.search_encounter(telegram_user_id=7)

    assert captured["path"] == "/encounter/search"
    assert captured["headers"]["x-telegram-user-id"] == "7"
    assert result["enemy_type"] == "wolf"


async def test_search_boss_encounter_sends_telegram_header():
    handler, captured = _echo_handler(200, {"combat_session_id": 9, "enemy_type": "boss"})
    client = make_client(handler)

    result = await client.search_boss_encounter(telegram_user_id=7)

    assert captured["path"] == "/encounter/search_boss"
    assert captured["headers"]["x-telegram-user-id"] == "7"
    assert result["enemy_type"] == "boss"


async def test_start_combat_path_and_header():
    handler, captured = _echo_handler(200, {"status": "awaiting_confirmation"})
    client = make_client(handler)

    await client.start_combat(telegram_user_id=7, combat_session_id=5)

    assert captured["path"] == "/combat/5/start"
    assert captured["headers"]["x-telegram-user-id"] == "7"


async def test_confirm_combat_sends_decision():
    handler, captured = _echo_handler(200, {"status": "active"})
    client = make_client(handler)

    await client.confirm_combat(telegram_user_id=7, combat_session_id=5, decision="fight")

    assert captured["path"] == "/combat/5/confirm"
    assert captured["json"] == {"decision": "fight"}


async def test_take_turn_path_and_header():
    handler, captured = _echo_handler(200, {"status": "active", "text": "..."})
    client = make_client(handler)

    await client.take_turn(telegram_user_id=7, combat_session_id=5)

    assert captured["path"] == "/combat/5/turn"
    assert captured["headers"]["x-telegram-user-id"] == "7"
    assert captured["json"] == {"power_attack": False}


async def test_take_turn_sends_power_attack_flag():
    handler, captured = _echo_handler(200, {"status": "active", "text": "..."})
    client = make_client(handler)

    await client.take_turn(telegram_user_id=7, combat_session_id=5, power_attack=True)

    assert captured["json"] == {"power_attack": True}


async def test_flee_decision_sends_decision():
    handler, captured = _echo_handler(200, {"status": "finished"})
    client = make_client(handler)

    await client.flee_decision(telegram_user_id=7, combat_session_id=5, decision="continue")

    assert captured["path"] == "/combat/5/flee_decision"
    assert captured["json"] == {"decision": "continue"}


async def test_use_potion_sends_size_and_header():
    handler, captured = _echo_handler(200, {"status": "active", "current_turn": "enemy"})
    client = make_client(handler)

    await client.use_potion(telegram_user_id=7, combat_session_id=5, size="large")

    assert captured["path"] == "/combat/5/use_potion"
    assert captured["json"] == {"size": "large"}
    assert captured["headers"]["x-telegram-user-id"] == "7"


async def test_get_combat_session_path_and_header():
    handler, captured = _echo_handler(200, {"status": "active"})
    client = make_client(handler)

    await client.get_combat_session(telegram_user_id=7, combat_session_id=5)

    assert captured["path"] == "/combat/5"
    assert captured["headers"]["x-telegram-user-id"] == "7"


async def test_resume_combat_session_path_and_header():
    handler, captured = _echo_handler(200, {"status": "active", "text": "..."})
    client = make_client(handler)

    await client.resume_combat_session(telegram_user_id=7, combat_session_id=5)

    assert captured["method"] == "GET"
    assert captured["path"] == "/combat/5/resume"
    assert captured["headers"]["x-telegram-user-id"] == "7"


async def test_cancel_combat_session_path_and_header():
    captured = {}

    def handler(request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return httpx.Response(204)

    client = make_client(handler)

    result = await client.cancel_combat_session(telegram_user_id=7, combat_session_id=5)

    assert captured["method"] == "DELETE"
    assert captured["path"] == "/combat/5"
    assert captured["headers"]["x-telegram-user-id"] == "7"
    assert result is None


async def test_error_response_raises_api_error_with_detail():
    handler, _ = _echo_handler(404, {"detail": "combat session not found"})
    client = make_client(handler)

    with pytest.raises(ApiError) as exc_info:
        await client.get_combat_session(telegram_user_id=7, combat_session_id=999)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "combat session not found"


async def test_error_response_without_json_body_falls_back_to_text():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    client = make_client(handler)

    with pytest.raises(ApiError) as exc_info:
        await client.get_character(1)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "internal server error"
