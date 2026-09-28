"""Тесты роутера /character через FastAPI TestClient + изолированную SQLite."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import DEV_DEFAULT_API_KEY, get_db, require_api_key
from api.routers.character import router as character_router
from core import economy as ec
from db.models import Character, CombatSession, StatAllocationLog
from tests.api.conftest import override_get_db


def _set_character_economy(db_session_factory, character_id, *, gold=None, loot=None, potions_small=None, potions_large=None):
    db = db_session_factory()
    character = db.get(Character, character_id)
    if gold is not None:
        character.gold = gold
    if loot is not None:
        character.loot = loot
    if potions_small is not None:
        character.potions_small = potions_small
    if potions_large is not None:
        character.potions_large = potions_large
    db.commit()
    db.close()


def make_client(db_session_factory, *, bypass_api_key: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(character_router)
    app.dependency_overrides[get_db] = override_get_db(db_session_factory)
    if bypass_api_key:
        app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)


def test_create_character_returns_base_stats_and_starting_pool(db_session_factory):
    client = make_client(db_session_factory)
    response = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"})
    assert response.status_code == 201
    body = response.json()
    assert body["nickname"] == "Hero"
    assert body["level"] == 1
    assert body["strength"] == 3
    assert body["agility"] == 3
    assert body["luck"] == 1
    assert body["vitality"] == 3
    assert body["unspent_stat_points"] == 5
    assert body["hp_max"] == 50
    assert body["hp_current"] == 50


def test_create_character_defaults_language_to_ru(db_session_factory):
    # docs/notes.md — дефолт только ради тестов/обратной совместимости; бот
    # (реальный единственный клиент) передаёт его всегда явно.
    client = make_client(db_session_factory)
    response = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"})
    assert response.json()["language"] == "ru"


def test_create_character_respects_explicit_language(db_session_factory):
    client = make_client(db_session_factory)
    response = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero", "language": "en"})
    assert response.json()["language"] == "en"


def test_create_character_is_idempotent(db_session_factory):
    client = make_client(db_session_factory)
    first = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()
    second = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero again"}).json()
    assert first["id"] == second["id"]
    assert second["nickname"] == "Hero"  # не перезаписан вторым вызовом


def test_get_character_not_found(db_session_factory):
    client = make_client(db_session_factory)
    response = client.get("/character/999")
    assert response.status_code == 404


def test_get_character_returns_created_character(db_session_factory):
    client = make_client(db_session_factory)
    client.post("/character", json={"telegram_user_id": 42, "nickname": "Ally"})
    response = client.get("/character/42")
    assert response.status_code == 200
    assert response.json()["nickname"] == "Ally"


def test_get_character_active_combat_session_id_is_none_by_default(db_session_factory):
    client = make_client(db_session_factory)
    client.post("/character", json={"telegram_user_id": 42, "nickname": "Ally"})
    response = client.get("/character/42")
    assert response.json()["active_combat_session_id"] is None


def test_get_character_returns_active_combat_session_id_when_battling(db_session_factory):
    # docs/notes.md, п.48 — бот проверяет это поле при /start, чтобы
    # восстановить потерянный экран боя вместо обычного меню персонажа.
    client = make_client(db_session_factory)
    character_id = client.post("/character", json={"telegram_user_id": 42, "nickname": "Ally"}).json()["id"]

    db = db_session_factory()
    session = CombatSession(
        character_id=character_id, enemy_type="mouse", enemy_hp_current=20.0,
        character_hp_snapshot=50.0, status="active", current_turn="player", turn_log=[],
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    session_id = session.id
    db.close()

    response = client.get("/character/42")
    assert response.json()["active_combat_session_id"] == session_id


def test_get_character_ignores_finished_combat_sessions(db_session_factory):
    client = make_client(db_session_factory)
    character_id = client.post("/character", json={"telegram_user_id": 42, "nickname": "Ally"}).json()["id"]

    db = db_session_factory()
    session = CombatSession(
        character_id=character_id, enemy_type="mouse", enemy_hp_current=0.0,
        character_hp_snapshot=50.0, status="finished", result="victory", current_turn="player", turn_log=[],
    )
    db.add(session)
    db.commit()
    db.close()

    response = client.get("/character/42")
    assert response.json()["active_combat_session_id"] is None


def test_get_character_regenerates_hp_lazily(db_session_factory):
    client = make_client(db_session_factory)
    client.post("/character", json={"telegram_user_id": 7, "nickname": "Regen"})

    # Напрямую понижаем hp_current и отодвигаем last_hp_update_at в прошлое,
    # как будто персонаж давно не обращался к серверу.
    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 7).first()
    character.hp_current = 20.0
    character.last_hp_update_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=15)
    db.commit()
    db.close()

    response = client.get("/character/7")
    body = response.json()
    assert body["hp_current"] == pytest.approx(35.0, abs=0.5)  # 20 + ~15 сек * 1 HP/сек
    assert body["hp_max"] == 50


def test_allocate_point_decrements_pool_and_increments_stat(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()

    response = client.post(f"/character/{created['id']}/allocate_point", json={"stat": "strength"})
    assert response.status_code == 200
    body = response.json()["character"]
    assert body["strength"] == 4
    assert body["unspent_stat_points"] == 4


def test_allocate_point_logs_stat_and_level(db_session_factory):
    # docs/notes.md: раньше выбор стата при прокачке нигде не сохранялся,
    # только итоговое значение на персонаже — теперь пишем историю.
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()

    client.post(f"/character/{created['id']}/allocate_point", json={"stat": "luck"})

    db = db_session_factory()
    logs = db.query(StatAllocationLog).filter(StatAllocationLog.character_id == created["id"]).all()
    db.close()
    assert len(logs) == 1
    assert logs[0].stat == "luck"
    assert logs[0].level_at_time == 1


def test_allocate_point_unknown_stat_returns_422(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()

    response = client.post(f"/character/{created['id']}/allocate_point", json={"stat": "intelligence"})
    assert response.status_code == 422


def test_allocate_point_no_points_left_returns_400(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()

    for _ in range(5):  # тратим весь стартовый пул (5 очков)
        client.post(f"/character/{created['id']}/allocate_point", json={"stat": "strength"})

    response = client.post(f"/character/{created['id']}/allocate_point", json={"stat": "strength"})
    assert response.status_code == 400


def test_allocate_point_character_not_found_returns_404(db_session_factory):
    client = make_client(db_session_factory)
    response = client.post("/character/999/allocate_point", json={"stat": "strength"})
    assert response.status_code == 404


def test_sell_loot_adds_gold_and_clears_inventory(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()
    _set_character_economy(db_session_factory, created["id"], gold=3, loot={"mouse_pelt": 14, "wolf_fang": 3})

    response = client.post(f"/character/{created['id']}/sell_loot")

    assert response.status_code == 200
    body = response.json()["character"]
    assert body["gold"] == 3 + 14 * ec.LOOT_ITEM_PRICES["mouse_pelt"] + 3 * ec.LOOT_ITEM_PRICES["wolf_fang"]
    assert body["loot"] == {}


def test_sell_loot_empty_inventory_is_a_no_op(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()

    response = client.post(f"/character/{created['id']}/sell_loot")

    assert response.status_code == 200
    body = response.json()["character"]
    assert body["gold"] == 0
    assert body["loot"] == {}


def test_sell_loot_character_not_found_returns_404(db_session_factory):
    client = make_client(db_session_factory)
    response = client.post("/character/999/sell_loot")
    assert response.status_code == 404


def test_buy_potion_small_deducts_gold_and_increments_count(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()
    _set_character_economy(db_session_factory, created["id"], gold=100)

    response = client.post(f"/character/{created['id']}/buy_potion", json={"size": "small"})

    assert response.status_code == 200
    body = response.json()["character"]
    assert body["gold"] == 100 - ec.SMALL_POTION_PRICE
    assert body["potions_small"] == 1
    assert body["potions_large"] == 0


def test_buy_potion_large_deducts_gold_and_increments_count(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()
    _set_character_economy(db_session_factory, created["id"], gold=100)

    response = client.post(f"/character/{created['id']}/buy_potion", json={"size": "large"})

    assert response.status_code == 200
    body = response.json()["character"]
    assert body["gold"] == 100 - ec.LARGE_POTION_PRICE
    assert body["potions_large"] == 1


def test_buy_potion_not_enough_gold_returns_400_with_reason(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()
    _set_character_economy(db_session_factory, created["id"], gold=0)

    response = client.post(f"/character/{created['id']}/buy_potion", json={"size": "small"})

    assert response.status_code == 400
    assert response.json()["detail"] == "not_enough_gold"


def test_buy_potion_cap_reached_returns_400_with_distinct_reason(db_session_factory):
    # Даже с горой золота — если кап уже достигнут, причина именно
    # "cap_reached", не "not_enough_gold" (бот должен показать разное).
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()
    _set_character_economy(db_session_factory, created["id"], gold=10_000, potions_large=ec.LARGE_POTION_CAP)

    response = client.post(f"/character/{created['id']}/buy_potion", json={"size": "large"})

    assert response.status_code == 400
    assert response.json()["detail"] == "cap_reached"


def test_buy_potion_unknown_size_returns_422(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()

    response = client.post(f"/character/{created['id']}/buy_potion", json={"size": "medium"})

    assert response.status_code == 422


def test_buy_potion_character_not_found_returns_404(db_session_factory):
    client = make_client(db_session_factory)
    response = client.post("/character/999/buy_potion", json={"size": "small"})
    assert response.status_code == 404


def test_reset_character_archives_without_deleting_history(db_session_factory):
    # docs/notes.md, п.41 — "сброс" раньше удалял персонажа и каскадом всю
    # его историю (CombatSession/StatAllocationLog), теперь архивирует:
    # для аналитики (scripts/export_playtest_stats.py) история должна
    # пережить сброс.
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()
    client.post(f"/character/{created['id']}/allocate_point", json={"stat": "strength"})

    db = db_session_factory()
    session = CombatSession(
        character_id=created["id"],
        enemy_type="mouse",
        enemy_hp_current=20.0,
        character_hp_snapshot=50.0,
        status="active",
        current_turn="player",
        turn_log=[],
    )
    db.add(session)
    db.commit()
    db.close()

    response = client.delete("/character/1", params={"reason": "manual_reset"})
    assert response.status_code == 204

    # Архивный персонаж больше не "текущий" — обычное чтение его не находит.
    assert client.get("/character/1").status_code == 404

    db = db_session_factory()
    archived = db.get(Character, created["id"])
    assert archived is not None  # строка не удалена
    assert archived.is_active is False
    assert archived.archived_at is not None
    assert archived.archived_reason == "manual_reset"
    assert db.query(CombatSession).filter(CombatSession.character_id == created["id"]).count() == 1
    assert db.query(StatAllocationLog).filter(StatAllocationLog.character_id == created["id"]).count() == 1
    db.close()


def test_reset_character_with_boss_victory_reason(db_session_factory):
    client = make_client(db_session_factory)
    created = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()

    response = client.delete("/character/1", params={"reason": "boss_victory"})
    assert response.status_code == 204

    db = db_session_factory()
    archived = db.get(Character, created["id"])
    assert archived.archived_reason == "boss_victory"
    db.close()


def test_reset_character_requires_reason_query_param(db_session_factory):
    client = make_client(db_session_factory)
    client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"})

    response = client.delete("/character/1")
    assert response.status_code == 422


def test_reset_character_rejects_unknown_reason(db_session_factory):
    client = make_client(db_session_factory)
    client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"})

    response = client.delete("/character/1", params={"reason": "something_else"})
    assert response.status_code == 422


def test_reset_character_not_found_returns_404(db_session_factory):
    client = make_client(db_session_factory)
    response = client.delete("/character/999", params={"reason": "manual_reset"})
    assert response.status_code == 404


def test_create_character_after_reset_starts_fresh_row(db_session_factory):
    # telegram_user_id больше не UNIQUE (docs/notes.md, п.41) — после сброса
    # у одного пользователя накапливается несколько строк Character:
    # архивная (со всей историей) и новая активная.
    client = make_client(db_session_factory)
    first = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()
    client.post(f"/character/{first['id']}/allocate_point", json={"stat": "strength"})

    client.delete("/character/1", params={"reason": "manual_reset"})
    second = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()

    assert second["id"] != first["id"]
    assert second["strength"] == 3  # базовые статы, не унаследованные от прокачки первого

    db = db_session_factory()
    assert db.query(Character).filter(Character.telegram_user_id == 1).count() == 2
    db.close()


def test_require_api_key_without_override(db_session_factory):
    client = make_client(db_session_factory, bypass_api_key=False)

    no_header = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"})
    assert no_header.status_code in (401, 422)  # 422, если Header(...) считает поле отсутствующим

    wrong_key = client.post(
        "/character",
        json={"telegram_user_id": 1, "nickname": "Hero"},
        headers={"X-Internal-Api-Key": "wrong"},
    )
    assert wrong_key.status_code == 401

    right_key = client.post(
        "/character",
        json={"telegram_user_id": 1, "nickname": "Hero"},
        headers={"X-Internal-Api-Key": DEV_DEFAULT_API_KEY},
    )
    assert right_key.status_code == 201


def test_set_language_updates_character(db_session_factory):
    client = make_client(db_session_factory)
    character_id = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()["id"]

    response = client.post(f"/character/{character_id}/set_language", json={"language": "en"})

    assert response.status_code == 200
    assert response.json()["character"]["language"] == "en"


def test_set_language_persists_across_reads(db_session_factory):
    client = make_client(db_session_factory)
    character_id = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()["id"]
    client.post(f"/character/{character_id}/set_language", json={"language": "en"})

    response = client.get("/character/1")

    assert response.json()["language"] == "en"


def test_set_language_character_not_found(db_session_factory):
    client = make_client(db_session_factory)
    response = client.post("/character/999/set_language", json={"language": "en"})
    assert response.status_code == 404


def test_set_language_rejects_unknown_language(db_session_factory):
    client = make_client(db_session_factory)
    character_id = client.post("/character", json={"telegram_user_id": 1, "nickname": "Hero"}).json()["id"]

    response = client.post(f"/character/{character_id}/set_language", json={"language": "de"})

    assert response.status_code == 422
