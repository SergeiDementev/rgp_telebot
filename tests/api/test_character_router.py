"""Тесты роутера /character через FastAPI TestClient + изолированную SQLite."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import DEV_DEFAULT_API_KEY, get_db, require_api_key
from api.routers.character import router as character_router
from db.models import Character
from tests.api.conftest import override_get_db


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
