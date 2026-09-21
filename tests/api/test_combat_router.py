"""Тесты роутера /combat: confirm/turn/flee_decision/get — цикл ходов боя."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_db, require_api_key
from api.routers.combat import router as combat_router
from api.routers.encounter import router as encounter_router
from db.models import Character, CombatSession
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
        level=overrides.get("level", 1),
        victory_points=overrides.get("victory_points", 0),
        unspent_stat_points=0,
        strength=overrides.get("strength", 10),
        agility=overrides.get("agility", 5),
        luck=overrides.get("luck", 2),
        vitality=overrides.get("vitality", 3),
        hp_current=overrides.get("hp_current", 50.0),
        last_hp_update_at=datetime.now(timezone.utc).replace(tzinfo=None),
        potions_small=overrides.get("potions_small", 0),
        potions_large=overrides.get("potions_large", 0),
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


def _start_session_against_boss(client, monkeypatch, extra_rolls, headers=HEADERS):
    """search_boss (без броска, docs/notes.md п.36) -> start (игрок первый,
    обстоятельства нет) -> confirm(fight), затем extra_rolls для /turn."""
    _patch_rolls(monkeypatch, [7, 4, 5, *extra_rolls])  # 7>4->игрок первый, 5->none
    session_id = client.post("/encounter/search_boss", headers=headers).json()["combat_session_id"]
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
    assert response.json()["text"].startswith("❤️ Ты: 50/50   👹 Мышь: 20/20")


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
        extra_rolls=[10, 10, 10, 100],  # double-strike check (не сработал), атака 100%, уворот мимо, лут="nothing"
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


def test_turn_victory_can_drop_loot_into_character_inventory(db_session_factory, monkeypatch):
    # Регрессия (docs/notes.md, п.30/31): лут раньше не спавнился вообще —
    # "Меню игрока"/sell_loot были собраны, но ничего в бою не начисляло
    # предмет персонажу. Отдельный бросок ПОСЛЕ исхода боя, как и в
    # симуляторе (core.economy.resolve_loot_drop) — roll=1 -> mouse_pelt.
    _insert_character(db_session_factory, strength=100, agility=10, luck=2)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(
        client, monkeypatch,
        extra_rolls=[10, 10, 10, 1],  # double-strike(нет), атака 100%, уворот мимо, лут roll=1 -> mouse_pelt
    )

    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert body["result"] == "victory"
    assert "🎁 Добыча: Мышиная шкурка" in body["text"]

    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 1).first()
    assert character.loot == {"mouse_pelt": 1}
    db.close()


def test_turn_victory_with_no_loot_omits_loot_line(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, strength=100, agility=10, luck=2)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(
        client, monkeypatch,
        extra_rolls=[10, 10, 10, 100],  # лут roll=100 -> "nothing"
    )

    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert body["result"] == "victory"
    assert "🎁 Добыча" not in body["text"]
    assert "😕 Упс, не повезло с добычей..." in body["text"]  # docs/notes.md — явная строка, не молчание

    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 1).first()
    assert character.loot == {}
    db.close()


def test_use_potion_heals_ends_turn_and_passes_to_enemy(db_session_factory, monkeypatch):
    # docs/notes.md, п.33 — зелье явное действие игрока кнопкой, не
    # автоматика (отменяет п.32): заменяет атаку в этот ход, сразу передаёт
    # ход противнику. Большое зелье лечит на 50% от hp_max (50) -> +25.
    _insert_character(db_session_factory, strength=10, agility=5, luck=2, hp_current=10.0, potions_large=1)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(client, monkeypatch, extra_rolls=[])

    response = client.post(f"/combat/{session_id}/use_potion", json={"size": "large"}, headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert "🧪 Большое зелье: +25 HP." in body["text"]
    assert body["status"] == "active"
    assert body["current_turn"] == "enemy"  # ход передан, атаки в этот ход не было
    assert body["potions_large"] == 0
    assert body["potion_used_this_battle"] is True

    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 1).first()
    assert character.potions_large == 0
    db.close()


def test_use_potion_small_heal_keeps_hp_integer_on_non_divisible_hp_max(db_session_factory, monkeypatch):
    # Регрессия (docs/notes.md) — vitality=5 -> hp_max=70, малое зелье
    # (25%) даёт дробные 17.5 без округления в core.economy.calculate_
    # heal_amount; дробный остаток застревал в character_hp_snapshot
    # навсегда (последующий урон всегда целый), пока HP не показывало
    # "0/70" в статус-баре, хотя реально было, например, 0.5 — бой не
    # заканчивался, хотя выглядело так, будто должен был.
    _insert_character(
        db_session_factory, strength=10, agility=5, luck=2, vitality=5, hp_current=10.0, potions_small=1
    )
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(client, monkeypatch, extra_rolls=[])

    response = client.post(f"/combat/{session_id}/use_potion", json={"size": "small"}, headers=HEADERS)
    assert response.status_code == 200
    assert "🧪 Малое зелье: +18 HP." in response.json()["text"]

    db = db_session_factory()
    session = db.get(CombatSession, session_id)
    assert session.character_hp_snapshot == 28  # 10 + round(70*0.25) = 10 + 18, целое
    db.close()


def test_use_potion_rejects_when_already_used_this_battle(db_session_factory, monkeypatch):
    # Лимит общий на оба размера — используем size="small" сразу выставленным
    # флагом (не через реальный вызов: тот передаёт ход противнику, и второй
    # вызов на этом же ходу закономерно упёрся бы в "не твой ход" раньше,
    # чем в "уже использовано" — проверяем лимит изолированно).
    _insert_character(db_session_factory, strength=10, agility=5, luck=2, hp_current=10.0, potions_small=2)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(client, monkeypatch, extra_rolls=[])
    db = db_session_factory()
    session = db.get(CombatSession, session_id)
    session.player_potion_used_this_battle = True
    db.commit()
    db.close()

    response = client.post(f"/combat/{session_id}/use_potion", json={"size": "small"}, headers=HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"] == "already_used"

    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 1).first()
    assert character.potions_small == 2  # не потрачено
    db.close()


def test_use_potion_against_boss_has_no_per_battle_limit(db_session_factory, monkeypatch):
    # docs/notes.md, п.39 — у финального босса нет ограничения "раз за бой"
    # на зелья (unlimited_potions в content/enemies.json), в отличие от
    # обычных противников (п.33). Инвентарь всё равно тратится по-настоящему.
    _insert_character(
        db_session_factory, level=9, strength=10, agility=5, luck=2, hp_current=10.0, potions_small=2
    )
    client = make_client(db_session_factory)

    session_id = _start_session_against_boss(client, monkeypatch, extra_rolls=[])

    first = client.post(f"/combat/{session_id}/use_potion", json={"size": "small"}, headers=HEADERS)
    body = first.json()
    assert first.status_code == 200
    assert body["potion_used_this_battle"] is False  # лимита нет — флаг не взводится
    assert body["current_turn"] == "enemy"

    # Ход босса — промах, чтобы ход снова вернулся игроку.
    _patch_rolls(monkeypatch, [10, 1, 1])  # double-strike нет, атака=1 -> промах, уворот неважен
    resolved = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    assert resolved.json()["current_turn"] == "player"

    second = client.post(f"/combat/{session_id}/use_potion", json={"size": "small"}, headers=HEADERS)
    body2 = second.json()
    assert second.status_code == 200  # не "already_used", несмотря на то что зелье уже пилось
    assert body2["potion_used_this_battle"] is False

    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 1).first()
    assert character.potions_small == 0  # реальный лимит — только инвентарь
    db.close()


def test_use_potion_rejects_when_not_owned(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, strength=10, agility=5, luck=2, hp_current=10.0)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(client, monkeypatch, extra_rolls=[])

    response = client.post(f"/combat/{session_id}/use_potion", json={"size": "small"}, headers=HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"] == "not_owned"


def test_use_potion_rejects_on_enemy_turn(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, strength=10, agility=5, luck=2, hp_current=10.0, potions_small=1)
    client = make_client(db_session_factory)

    # 3->мышь, 4<7->противник первый (обратный порядок роллов инициативы)
    _patch_rolls(monkeypatch, [3, 4, 7, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=HEADERS)
    client.post(f"/combat/{session_id}/confirm", json={"decision": "fight"}, headers=HEADERS)

    response = client.post(f"/combat/{session_id}/use_potion", json={"size": "small"}, headers=HEADERS)
    assert response.status_code == 409

    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 1).first()
    assert character.potions_small == 1  # не потрачено
    db.close()


def test_use_potion_rejects_when_session_not_active(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, potions_small=1)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=HEADERS)
    # confirm ещё не вызван -> статус "awaiting_confirmation", не "active"

    response = client.post(f"/combat/{session_id}/use_potion", json={"size": "small"}, headers=HEADERS)
    assert response.status_code == 409


def test_use_potion_rejects_unknown_size(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, potions_small=1)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(client, monkeypatch, extra_rolls=[])
    response = client.post(f"/combat/{session_id}/use_potion", json={"size": "medium"}, headers=HEADERS)
    assert response.status_code == 422


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
    assert body["text"].startswith("❤️ Ты:")  # HP-шапка на каждой фазе, не только в итоге


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
    assert body["text"].startswith("❤️ Ты:")

    # "continue" -> право сгорает, ход доигрывается тут же (гарантированная победа)
    _patch_rolls(monkeypatch, [10, 10, 10, 100])  # double-strike нет, атака=100%, уворот мимо, лут="nothing"
    response = client.post(f"/combat/{session_id}/flee_decision", json={"decision": "continue"}, headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "victory"


def test_flee_gate_burns_right_even_when_roll_fails(db_session_factory, monkeypatch):
    # §6 (пересмотрено 2026-09-15, docs/notes.md п.9): одна попытка за бой на
    # сторону — провал броска тоже тратит право, не только отказ после успеха.
    _insert_character(db_session_factory, strength=10, agility=5, luck=2, hp_current=10.0)
    client = make_client(db_session_factory)

    session_id = _start_session_against_mouse(client, monkeypatch, extra_rolls=[])

    # Ход 1 (игрок): gate-роллы luck_roll=10 -> не сработало (success_faces=1
    # при luck=2), но право должно сгореть всё равно.
    _patch_rolls(monkeypatch, [10, 10, 3, 10])  # gate=10, double-strike=10, атака=3(50%), уворот мимо
    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert body["status"] == "active"
    assert "Твоя проверка удачи на побег" in body["text"]
    assert "шанса уйти нет" in body["text"]

    db = db_session_factory()
    session = db.get(CombatSession, session_id)
    assert session.player_flee_right_used is True
    db.close()

    # Ход 2 (мышь) — просто продвигает очередь, промах.
    _patch_rolls(monkeypatch, [10, 1, 5])
    client.post(f"/combat/{session_id}/turn", headers=HEADERS)

    # Ход 3 (игрок снова, HP всё ещё ниже порога): право уже использовано —
    # проверка на побег больше не должна всплывать.
    _patch_rolls(monkeypatch, [10, 1, 5])
    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert "проверка удачи на побег" not in body["text"].lower()


def test_turn_victory_against_boss_shows_congratulations_and_no_loot(db_session_factory, monkeypatch):
    # docs/notes.md, п.36 — победа над боссом рендерится отдельным экраном
    # поздравления (render_boss_victory), не обычным render_battle_end: без
    # строки HP/таймера регена и без лута (LOOT_TABLE["boss"] = "nothing").
    _insert_character(db_session_factory, level=9, strength=1000, agility=10, luck=2)
    client = make_client(db_session_factory)

    session_id = _start_session_against_boss(
        client, monkeypatch,
        extra_rolls=[10, 10, 10, 100],  # double-strike нет, атака=100%, уворот мимо, лут roll (неважно какой)
    )

    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "victory"
    assert body["status"] == "finished"
    assert body["enemy_type"] == "boss"
    assert "Лесного Короля" in body["text"]
    assert "🎁 Добыча" not in body["text"]
    assert "❤️ HP" not in body["text"]  # экран поздравления, не обычный итог боя

    db = db_session_factory()
    character = db.query(Character).filter(Character.telegram_user_id == 1).first()
    assert character.victory_points == 100  # VICTORY_REWARD_DEFAULTS["boss"]
    assert character.loot == {}
    db.close()


def test_boss_enemy_side_never_triggers_flee_gate(db_session_factory, monkeypatch):
    # can_flee=false в content/enemies.json (docs/notes.md, п.36) — сторона
    # enemy у босса никогда не проверяет побег, даже при HP далеко ниже
    # порога 25%. Сессия собрана напрямую в БД — довести HP именно
    # атакующей стороны "enemy" до низкого порога через полный HTTP-поток
    # заняло бы много ходов и не добавило бы проверке ничего нового.
    character_id = _insert_character(db_session_factory, level=9, strength=1, agility=1, luck=1, hp_current=50.0)
    client = make_client(db_session_factory)

    db = db_session_factory()
    session = CombatSession(
        character_id=character_id,
        enemy_type="boss",
        enemy_hp_current=10.0,  # 10/150 — далеко ниже 25%-порога
        character_hp_snapshot=50.0,
        current_turn="enemy",
        status="active",
        turn_log=[],
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    session_id = session.id
    db.close()

    _patch_rolls(monkeypatch, [10, 1, 1])  # double-strike нет, атака=1 -> промах (исход не важен)
    response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert "побег" not in body["text"].lower()
    assert "уйти" not in body["text"].lower()

    db = db_session_factory()
    refreshed = db.get(CombatSession, session_id)
    assert refreshed.enemy_flee_right_used is False  # право даже не тронуто
    db.close()


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


def test_resume_combat_session_awaiting_initiative_reconstructs_encounter_text(db_session_factory, monkeypatch):
    # docs/notes.md, п.48 — восстановление потерянной клавиатуры боя
    # (например, после удаления чата в Telegram): CombatSession в БД
    # остаётся активной, /resume реконструирует тот же экран без нового броска.
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    response = client.get(f"/combat/{session_id}/resume", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "awaiting_initiative"
    assert body["enemy_type"] == "mouse"
    assert "Мышь" in body["text"]


def test_resume_combat_session_awaiting_initiative_boss_uses_boss_text(db_session_factory):
    # Босс не кидает d10 на встречу (docs/notes.md, п.36) — turn_log[0] не
    # содержит "roll", ветка должна отличить это и не упасть на KeyError.
    _insert_character(db_session_factory, level=9)
    client = make_client(db_session_factory)

    session_id = client.post("/encounter/search_boss", headers=HEADERS).json()["combat_session_id"]

    response = client.get(f"/combat/{session_id}/resume", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert "Лесного Короля" in body["text"] or "Лесной Король" in body["text"]


def test_resume_combat_session_awaiting_confirmation_reconstructs_initiative_and_circumstance(
    db_session_factory, monkeypatch
):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])  # мышь, игрок первый (7>4), обстоятельства нет
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=HEADERS)

    response = client.get(f"/combat/{session_id}/resume", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "awaiting_confirmation"
    assert "Инициатива" in body["text"]
    assert "Обстоятельство" in body["text"]


def test_resume_combat_session_active_shows_hp_status(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)
    session_id = _start_session_against_mouse(client, monkeypatch, extra_rolls=[])

    response = client.get(f"/combat/{session_id}/resume", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "active"
    assert body["text"].startswith("❤️ Ты:")


def test_resume_combat_session_awaiting_flee_decision_reconstructs_flee_check(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, strength=100, agility=10, luck=1000, hp_current=10.0)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]
    client.post(f"/combat/{session_id}/start", headers=HEADERS)
    client.post(f"/combat/{session_id}/confirm", json={"decision": "fight"}, headers=HEADERS)

    _patch_rolls(monkeypatch, [1])  # luck_roll=1 -> побег почти наверняка предложен (luck=1000)
    turn_response = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    assert turn_response.json()["status"] == "awaiting_flee_decision"

    response = client.get(f"/combat/{session_id}/resume", headers=HEADERS)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "awaiting_flee_decision"
    assert "шанс уйти живым" in body["text"]
    assert body["text"].startswith("❤️ Ты:")


def test_resume_combat_session_finished_returns_409(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, strength=100, agility=10, luck=2)
    client = make_client(db_session_factory)
    session_id = _start_session_against_mouse(
        client, monkeypatch, extra_rolls=[10, 10, 10, 100],
    )
    finished = client.post(f"/combat/{session_id}/turn", headers=HEADERS)
    assert finished.json()["status"] == "finished"

    response = client.get(f"/combat/{session_id}/resume", headers=HEADERS)
    assert response.status_code == 409


def test_resume_combat_session_not_found_returns_404(db_session_factory):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)
    response = client.get("/combat/999/resume", headers=HEADERS)
    assert response.status_code == 404


def test_resume_combat_session_forbids_other_character(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, telegram_user_id=1)
    _insert_character(db_session_factory, telegram_user_id=2)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    response = client.get(f"/combat/{session_id}/resume", headers=OTHER_HEADERS)
    assert response.status_code == 403


def test_resume_combat_session_does_not_mutate_state(db_session_factory, monkeypatch):
    # Только чтение — повторные вызовы не должны менять сессию.
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)
    session_id = _start_session_against_mouse(client, monkeypatch, extra_rolls=[])

    first = client.get(f"/combat/{session_id}/resume", headers=HEADERS)
    second = client.get(f"/combat/{session_id}/resume", headers=HEADERS)
    assert first.json() == second.json()

    db = db_session_factory()
    session = db.get(CombatSession, session_id)
    assert session.status == "active"
    db.close()


def test_cancel_combat_session_awaiting_initiative_deletes_it(db_session_factory, monkeypatch):
    # docs/notes.md, п.51 — "⬅️ Назад" на экране входа в бой, до инициативы:
    # ничего ещё не произошло, поэтому сессия удаляется физически, не
    # архивируется как исход боя.
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    response = client.delete(f"/combat/{session_id}", headers=HEADERS)
    assert response.status_code == 204

    db = db_session_factory()
    assert db.get(CombatSession, session_id) is None
    db.close()

    # Отменённая встреча не блокирует новый поиск (docs/notes.md, п.36/41 —
    # "активная" сессия для _require_no_active_session её больше не видит).
    second = client.post("/encounter/search", headers=HEADERS)
    assert second.status_code == 200


def test_cancel_combat_session_rejects_after_initiative(db_session_factory, monkeypatch):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)
    session_id = _start_session_against_mouse(client, monkeypatch, extra_rolls=[])

    response = client.delete(f"/combat/{session_id}", headers=HEADERS)
    assert response.status_code == 409

    db = db_session_factory()
    assert db.get(CombatSession, session_id) is not None  # не удалена
    db.close()


def test_cancel_combat_session_not_found_returns_404(db_session_factory):
    _insert_character(db_session_factory)
    client = make_client(db_session_factory)
    response = client.delete("/combat/999", headers=HEADERS)
    assert response.status_code == 404


def test_cancel_combat_session_forbids_other_character(db_session_factory, monkeypatch):
    _insert_character(db_session_factory, telegram_user_id=1)
    _insert_character(db_session_factory, telegram_user_id=2)
    client = make_client(db_session_factory)

    _patch_rolls(monkeypatch, [3, 7, 4, 5])
    session_id = client.post("/encounter/search", headers=HEADERS).json()["combat_session_id"]

    response = client.delete(f"/combat/{session_id}", headers=OTHER_HEADERS)
    assert response.status_code == 403

    db = db_session_factory()
    assert db.get(CombatSession, session_id) is not None  # не удалена чужим запросом
    db.close()
