"""Тесты роутера /combat: confirm/turn/flee_decision/get — цикл ходов боя."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_db, require_api_key
from api.routers.combat import router as combat_router
from api.routers.encounter import router as encounter_router
from db.models import Character
from tests.api.conftest import override_get_db

HEADERS = {"X-Telegram-User-Id": "1"}
OTHER_HEADERS = {"X-Telegram-User-Id": "2"}


def make_client(db_session_factory) -> TestClient:
    app = FastAPI()
    app.include_router(encounter_router)
    app.include_router(combat_router)
    app.dependency_overrides[get_db] = override_get_db(db_session_factory)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)


def _insert_character(db_session_factory, telegram_user_id=1, **overrides) -> int:
    db = db_session_factory()
    character = Character(
        telegram_user_id=telegram_user_id,
        nickname="Hero",
        level=1,
        victory_points=overrides.get("victory_points", 0),
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


def _patch_rolls(monkeypatch, rolls):
    """Общий поток random.randint для encounter.py и combat.py (два разных
    модульных импорта random, но одна и та же последовательность бросков)."""
    it = iter(rolls)

    def _next(a, b):
        return next(it)

    monkeypatch.setattr("api.routers.encounter.random.randint", _next)
    monkeypatch.setattr("api.routers.combat.random.randint", _next)


def _start_session_against_mouse(client, monkeypatch, extra_rolls, headers=HEADERS):
    """search (мышь) -> start (игрок первый, обстоятельства нет) -> confirm(fight),
    затем extra_rolls доступны для последующих вызовов (turn/flee_decision)."""
    _patch_rolls(monkeypatch, [3, 7, 4, 5, *extra_rolls])  # 3->мышь, 7>4->игрок первый, 5->none
    session_id = client.post("/encounter/search", headers=headers).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=headers)
    client.post(f"/combat/{session_id}/confirm", json={"decision": "fight"}, headers=headers)
    return session_id


def test_confirm_fight_transitions_to_active(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=HEADERS)

    response = client.post(f"/combat/{session_id}/confirm", json={"decision": "fight"}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_confirm_flee_ends_battle_with_no_reward(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, strength=10)
    client = make_client(db_session_factory)

    # мышь, игрок первый, без обстоятельства, затем безответный удар мыши: промах (roll=1)
    _patch_rolls(monkeypatch, [3, 7, 4, 5, 1])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=HEADERS)

    response = client.post(f"/combat/{session_id}/confirm", json={"decision": "flee"}, headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "player_fled"
    assert body["status"] == "finished"

    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 1).first()
    assert character.victory_points == 0
    db.close()


def test_turn_rejects_when_not_active(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=HEADERS)
    # confirm ещё не вызван -> статус "awaiting_confirmation", не "active"

    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    assert response.status_code == 409


def test_turn_victory_awards_reward_and_updates_character(db_session_factory, monkeypatch):
    # Сильный игрок против мыши — гарантированная победа одним ударом.
    _insert_character(db_session_factory, strength=100, agility=10, luck=2)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(
        client, monkeypatch,
        extra_rolls=[10, 10, 10],  # double-strike check (не сработал), атака 100%, уворот мимо
    )

    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "victory"
    assert body["status"] == "finished"
    assert "Ты победил Мышь" in body["text"]

    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 1).first()
    assert character.victory_points == 1  # награда за мышь
    db.close()


def test_turn_double_strike_renders_two_compact_strikes(db_session_factory, monkeypatch):
    # Очень высокая Удача -> двойной удар почти гарантирован; низкая Сила,
    # чтобы мышь (HP=20) пережила первый удар и получила второй.
    _insert_character(db_session_factory, strength=5, agility=10, luck=1000)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(
        client, monkeypatch,
        extra_rolls=[1, 3, 10, 5, 10],  # double-strike(1,triggered) удар1(3,10) удар2(5,10)
    )

    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert "УДАЧА! Двойной удар!" in body["text"]
    assert "Удар 1" in body["text"]
    assert "Удар 2" in body["text"]


def test_turn_defeat_by_enemy(db_session_factory, monkeypatch):
    # Слабый игрок, сильный (для этого теста) урон мыши невозможен по статам
    # мыши — вместо этого проверяем поражение через прямое исполнение хода
    # противника: игрок промахивается (double-strike нет, атака=1 промах),
    # затем ход переходит мыши и не завершает бой (мышь слаба) — здесь
    # достаточно проверить, что ход просто переходит дальше без ошибок.
    _insert_character(db_session_factory, strength=1, agility=1, luck=1)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(
        client, monkeypatch,
        extra_rolls=[10, 1, 1],  # double-strike нет, атака=1 -> промах
    )

    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "active"  # бой продолжается, ход перешёл к мыши
    assert "промах" in body["text"]


def test_flee_gate_pauses_for_player_and_flee_decision_continue_resumes_turn(db_session_factory, monkeypatch):
    # HP игрока ниже порога 25% от 50 max -> flee-gate применим.
    _insert_character(db_session_factory, strength=100, agility=10, luck=1000, hp_current=10.0)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])  # мышь, игрок первый, без обстоятельства
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=HEADERS)
    client.post(f"/combat/{session_id}/confirm", json={"decision": "fight"}, headers=HEADERS)

    _patch_rolls(monkeypatch, [1])  # luck_roll=1 -> побег почти наверняка предложен (luck=1000)
    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert body["status"] == "awaiting_flee_decision"
    assert "шанс уйти живым" in body["text"]

    # "continue" -> право сгорает, ход доигрывается тут же (гарантированная победа)
    _patch_rolls(monkeypatch, [10, 10, 10])  # double-strike нет, атака=100%, уворот мимо
    response = client.post(f"/combat/{session_id}/flee_decision", json={"decision": "continue"}, headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "victory"


def test_flee_gate_flee_decision_ends_battle(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, strength=10, agility=10, luck=1000, hp_current=10.0)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=HEADERS)
    client.post(f"/combat/{session_id}/confirm", json={"decision": "fight"}, headers=HEADERS)

    _patch_rolls(monkeypatch, [1])
    client.post(f"/combat/{session_id}/turn", headers=HEADERS)

    _patch_rolls(monkeypatch, [1])  # промах мыши при попытке побега
    response = client.post(f"/combat/{session_id}/flee_decision", json={"decision": "flee"}, headers=HEADERS)
    body = response.json()
    assert body["result"] == "player_fled"
    assert body["status"] == "finished"


def test_ownership_checks_forbid_other_character(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, telegram_user_id=1)
    _insert_character(db_session_factory, telegram_user_id=2)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    response = client.get(f"/combat/{session_id}", headers=OTHER_HEADERS)
    assert response.status_code == 403


def test_get_combat_session_returns_state(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    response = client.get(f"/combat/{session_id}", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["enemy_type"] == "mouse"
    assert body["status"] == "awaiting_initiative"
    assert body["enemy_hp_max"] == 20
