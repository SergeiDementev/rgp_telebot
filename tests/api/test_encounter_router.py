"""Тесты роутеров /encounter/search и /combat/{id}/start."""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_db, require_api_key
from api.routers.encounter import router as encounter_router
from core import progression as pr
from db.models import Character, CombatSession
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
        level=overrides.get("level", 1),
        victory_points=0,
        unspent_stat_points=0,
        strength=overrides.get("strength", 10),
        agility=overrides.get("agility", 5),
        luck=overrides.get("luck", 2),
        vitality=overrides.get("vitality", 3),
        hp_current=overrides.get("hp_current", 50.0),
        last_hp_update_at=datetime.now(timezone.utc).replace(tzinfo=None),
        potions_small=overrides.get("potions_small", 0),
        potions_large=overrides.get("potions_large", 0),
        language=overrides.get("language", "ru"),
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


def test_search_encounter_includes_potion_snapshot(db_session_factory):
    # docs/notes.md, п.51 — бот показывает запас зелий на экране входа в
    # бой, без отдельного GET /character.
    _insert_character(db_session_factory, potions_small=2, potions_large=1)
    client = make_client(db_session_factory)

    response = client.post("/encounter/search", headers=HEADERS)
    body = response.json()
    assert body["potions_small"] == 2
    assert body["potions_large"] == 1


def test_search_encounter_includes_character_language(db_session_factory):
    # docs/notes.md — бот использует это поле, чтобы выставить локаль перед
    # построением клавиатуры в хендлерах, которые сами персонажа не
    # запрашивают (search_encounter и т.п.) — без него клавиатура
    # ориентировалась бы на язык клиента Telegram, а не на явно выбранный
    # язык персонажа.
    _insert_character(db_session_factory, language="en")
    client = make_client(db_session_factory)

    response = client.post("/encounter/search", headers=HEADERS)

    assert response.json()["language"] == "en"


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

    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: 8)  # 6-8 -> волк
    response = client.post("/encounter/search", headers=HEADERS)
    assert response.json()["enemy_type"] == "wolf"


def test_search_encounter_shifts_odds_by_character_level(db_session_factory, monkeypatch):
    # §6 gameplay_loop_mvp.md, пересмотрено 2026-09-16: на 1 уровне грань 8 —
    # ещё волк (мышь 1-5, волк 6-8, кабан 9-10), а на позднем уровне та же
    # грань 8 уже кабан (мышь 1-2, волк 3-5, кабан 6-10) — пропорции сместились.
    _insert_character(db_session_factory, telegram_user_id=1, level=1)
    _insert_character(db_session_factory, telegram_user_id=2, level=9)
    client = make_client(db_session_factory)

    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: 8)

    low_level_response = client.post("/encounter/search", headers={"X-Telegram-User-Id": "1"})
    high_level_response = client.post("/encounter/search", headers={"X-Telegram-User-Id": "2"})

    assert low_level_response.json()["enemy_type"] == "wolf"
    assert high_level_response.json()["enemy_type"] == "boar"


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
    assert body["enemy_type"] == "wolf"  # docs/notes.md, п.40 — бот решает по нему, показывать ли автобой
    assert body["text"]


def test_start_combat_includes_character_language(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, language="en")
    client = make_client(db_session_factory)

    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: 8)
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    rolls = iter([7, 4, 5])
    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: next(rolls))
    response = client.post(f"/combat/{session_id}/start", headers=HEADERS)

    assert response.json()["language"] == "en"


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

    # 5,5 -> ничья, перебрасываем; 7,4 -> игрок первый; 5 -> обстоятельства нет
    rolls = iter([5, 5, 7, 4, 5])
    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: next(rolls))

    response = client.post(f"/combat/{session_id}/start", headers=HEADERS)
    body = response.json()
    assert body["first_role"] == "player"
    assert body["player_strength_modifier"] == 1.0
    assert body["enemy_strength_modifier"] == 1.0


def test_start_combat_against_boss_skips_circumstance(db_session_factory, monkeypatch):
    # docs/notes.md, п.56 — финальный босс без обстоятельства вообще
    # (has_circumstance=false в content/enemies.json): ни строки в тексте,
    # ни лишнего броска, оба модификатора Силы остаются 1.0.
    _insert_character(db_session_factory, level=pr.BOSS_LEVEL_REQUIREMENT)
    client = make_client(db_session_factory)

    session_id = client.post("/encounter/search_boss", headers=HEADERS).json()["combat_session_id"]

    rolls = iter([7, 4])  # только инициатива — если бы кинули обстоятельство, next(rolls) упал бы на StopIteration
    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: next(rolls))

    response = client.post(f"/combat/{session_id}/start", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["player_strength_modifier"] == 1.0
    assert body["enemy_strength_modifier"] == 1.0
    assert "Обстоятельство" not in body["text"]  # ни "без происшествий", ни buff/debuff — строки нет вообще

    db = db_session_factory()
    session = db.query(CombatSession).filter(CombatSession.id == session_id).first()
    assert session.circumstance_outcome is None
    assert session.circumstance_roller is None
    assert all(entry["type"] != "circumstance" for entry in session.turn_log)
    db.close()


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


def test_search_boss_encounter_creates_session_at_any_level(db_session_factory):
    # docs/notes.md, п.69 — экран входа доступен на любом уровне, порог
    # проверяется дальше, на POST /combat/{id}/start.
    _insert_character(db_session_factory, level=1, potions_small=2, potions_large=1)
    client = make_client(db_session_factory)

    response = client.post("/encounter/search_boss", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["enemy_type"] == "boss"
    assert body["status"] == "awaiting_initiative"
    assert body["text"]
    # docs/notes.md, п.51 — запас зелий на экране входа в бой с боссом.
    assert body["potions_small"] == 2
    assert body["potions_large"] == 1


def test_start_combat_against_boss_below_required_level_returns_403(db_session_factory):
    # docs/notes.md, п.69 — порог уровня снова здесь, не на
    # search_boss_encounter. Сессия остаётся в awaiting_initiative —
    # "⬅️ Назад" на предыдущем экране по-прежнему работает.
    _insert_character(db_session_factory, level=pr.BOSS_LEVEL_REQUIREMENT - 1)
    client = make_client(db_session_factory)

    session_id = client.post("/encounter/search_boss", headers=HEADERS).json()["combat_session_id"]
    response = client.post(f"/combat/{session_id}/start", headers=HEADERS)
    assert response.status_code == 403
    assert response.json()["detail"] == "level_too_low"

    db = db_session_factory()
    session = db.get(CombatSession, session_id)
    assert session.status == "awaiting_initiative"
    db.close()


def test_start_combat_against_boss_at_required_level_succeeds(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, level=pr.BOSS_LEVEL_REQUIREMENT)
    client = make_client(db_session_factory)

    session_id = client.post("/encounter/search_boss", headers=HEADERS).json()["combat_session_id"]
    rolls = iter([7, 4])
    monkeypatch.setattr("api.routers.encounter.random.randint", lambda a, b: next(rolls))
    response = client.post(f"/combat/{session_id}/start", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_confirmation"


def test_search_boss_encounter_rejects_second_active_session(db_session_factory):
    _insert_character(db_session_factory, level=pr.BOSS_LEVEL_REQUIREMENT)
    client = make_client(db_session_factory)

    first = client.post("/encounter/search_boss", headers=HEADERS)
    assert first.status_code == 200
    second = client.post("/encounter/search_boss", headers=HEADERS)
    assert second.status_code == 409


def test_search_boss_encounter_does_not_roll_dice(db_session_factory, monkeypatch):
    # Целенаправленная встреча, не случайный ростер (§6) — никакого броска.
    def _fail_randint(*_args, **_kwargs):
        raise AssertionError("search_boss_encounter must not roll dice")

    _insert_character(db_session_factory, level=pr.BOSS_LEVEL_REQUIREMENT)
    client = make_client(db_session_factory)
    monkeypatch.setattr("api.routers.encounter.random.randint", _fail_randint)

    response = client.post("/encounter/search_boss", headers=HEADERS)
    assert response.status_code == 200
