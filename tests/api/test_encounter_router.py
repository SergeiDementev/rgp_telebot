"""Тесты роутеров /encounter/search и /combat/{id}/start."""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_db, require_api_key
from api.routers.encounter import router as encounter_router
from db.models import Character
from tests.api.conftest import override_get_db

HEADERS = {"X-Telegram-User-Id": "1"}


def make_client(db_session_factory) -> TestClient:
    app = FastAPI()
    app.include_router(encounter_router)
    app.dependency_overrides[get_db] = override_get_db(db_session_factory)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)


def _insert_character(db_session_factory, telegram_user_id=1, **overrides) -> int:
    db = db_session_factory()
    character = Character(
        telegram_user_id=telegram_user_id,
        nickname="Hero",
        level=1,
        victory_points=0,
        unspent_stat_points=0,
        strength=overrides.get("strength", 10),
        agility=overrides.get("agility", 5),
        luck=overrides.get("luck", 2),
        vitality=overrides.get("vitality", 3),
        hp_current=overrides.get("hp_current", 50.0),
        last_hp_update_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    character_id = character.id
    db.close()
    return character_id


def test_search_encounter_creates_session(db_session_factory):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    response = client.post("/encounter/search", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["enemy_type"] in ("mouse", "wolf", "boar")
    assert body["status"] == "awaiting_initiative"
    assert body["combat_session_id"] > 0
    assert body["text"]


def test_search_encounter_without_character_returns_404(db_session_factory):
    client = make_client(db_session_factory)
    response = client.post("/encounter/search", headers=HEADERS)
    assert response.status_code == 404


def test_search_encounter_rejects_second_active_session(db_session_factory):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    first = client.post("/encounter/search", headers=HEADERS)
    assert first.status_code == 200

    second = client.post("/encounter/search", headers=HEADERS)
    assert second.status_code == 409


def test_search_encounter_specific_roll(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: 8)  # 7-9 -> волк
    response = client.post("/encounter/search", headers=HEADERS)
    assert response.json()["enemy_type"] == "wolf"


def test_start_combat_transitions_to_awaiting_confirmation(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: 8)
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    rolls = iter([7, 4, 5])
    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: next(rolls))
    response = client.post(f"/combat/{session_id}/start", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["first_role"] in ("player", "enemy")
    assert body["text"]


def test_start_combat_player_wins_initiative_and_rolls_buff(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: 8)
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    rolls = iter([7, 4, 9])  # player_roll=7 > enemy_roll=4 -> player first; circumstance=9 -> buff
    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: next(rolls))

    response = client.post(f"/combat/{session_id}/start", headers=HEADERS)
    body = response.json()
    assert body["first_role"] == "player"
    assert body["player_strength_modifier"] == 1.2
    assert body["enemy_strength_modifier"] == 1.0


def test_start_combat_rerolls_initiative_tie(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: 8)
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    # 5,5 -> ничья, перебрасываем; 7,4 -> игрок первый; 3 -> обстоятельства нет
    rolls = iter([5, 5, 7, 4, 3])
    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: next(rolls))

    response = client.post(f"/combat/{session_id}/start", headers=HEADERS)
    body = response.json()
    assert body["first_role"] == "player"
    assert body["player_strength_modifier"] == 1.0
    assert body["enemy_strength_modifier"] == 1.0


def test_start_combat_not_found(db_session_factory):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)
    response = client.post("/combat/999/start", headers=HEADERS)
    assert response.status_code == 404


def test_start_combat_wrong_owner_returns_403(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, telegram_user_id=1)
    _insert_character(db_session_factory, telegram_user_id=2)
    client = make_client(db_session_factory)

    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: 8)
    session_id = client.post("/encounter/search", headers={"X-Telegram-User-Id": "1"}).json()["combat_session_id"]

    response = client.post(f"/combat/{session_id}/start", headers={"X-Telegram-User-Id": "2"})
    assert response.status_code == 403


def test_start_combat_twice_returns_409(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: 8)
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    rolls = iter([7, 4, 5])
    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: next(rolls))
    first = client.post(f"/combat/{session_id}/start", headers=HEADERS)
    assert first.status_code == 200
    second = client.post(f"/combat/{session_id}/start", headers=HEADERS)
    assert second.status_code == 409
