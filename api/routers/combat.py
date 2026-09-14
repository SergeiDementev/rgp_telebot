"""Роутер /combat — confirm/turn/flee_decision/get: цикл ходов боя (§9 шаги 3-7).

Один HTTP-запрос = один шаг. `/turn` резолвит ровно один ход — чей бы он ни
был (игрока или бота): backend_plan.md §5 описывает это как "ход игрока
(+ автоматически ход бота, если следующая очередь его)" — это значит "если
сейчас очередь бота, его ход резолвится без доп. ввода", а не "всегда два
хода за раз". Кнопки "Атаковать"/"Защищаться" в gameplay_loop_mvp.md §9 —
косметика на стороне бота: обе дёргают один и тот же /turn, подпись бот
выбирает сам по `current_turn` из предыдущего ответа.

Константы формул (MAX_FACES/K) продублированы здесь из
scripts/simulate_combat.py — тот же набор черновых значений, ещё не
откалиброван (в отличие от ENEMY_PRESETS/STAT_POINTS_PER_LEVEL/порога
уровней, которые уже прошли этап 2). Если бы их менял, синхронизировать бы
пришлось оба места вручную — при переносе в реальный плейтест стоит
вынести в общее место.
"""

import random
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api import enemy_content, rendering
from api.dependencies import get_current_character, get_db, require_api_key
from api.schemas.combat import (
    CombatSessionOut,
    CombatTurnResponse,
    ConfirmRequest,
    FleeDecisionRequest,
)
from core import combat_mechanics as cm
from core import progression as pr
from db.models import Character, CombatSession

router = APIRouter(tags=["combat"], dependencies=[Depends(require_api_key)])

DODGE_MAX_FACES = 5
DODGE_K = 15
DOUBLE_STRIKE_K = 15
FLEE_MAX_FACES = 4
FLEE_K = 15


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load_owned_session(db: Session, combat_session_id: int, character: Character) -> CombatSession:
    session = db.get(CombatSession, combat_session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="combat session not found")
    if session.character_id != character.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your combat session")
    return session


def _finish_battle(session: CombatSession, character: Character, result: str, db: Session) -> str:
    """§10 combat_mechanics.md: применить исход — награда, уровни, синхронизация HP."""
    reward = pr.calculate_battle_reward(result, session.enemy_type)
    old_points = character.victory_points
    character.victory_points += reward
    levels_gained = pr.calculate_levels_gained(old_points, character.victory_points)
    character.level += levels_gained
    character.unspent_stat_points += pr.calculate_stat_points_gained(levels_gained)

    character.hp_current = session.character_hp_snapshot
    character.last_hp_update_at = _now()

    session.status = "finished"
    session.result = result

    hp_max = pr.calculate_hp_max(character.vitality)
    seconds_to_full = pr.time_to_full_hp(character.hp_current, hp_max)
    return rendering.render_battle_end(
        session.enemy_type, result, reward, character.victory_points, character.hp_current, hp_max, seconds_to_full
    )


def _check_flee_gate(session: CombatSession, character: Character, db: Session) -> Optional[dict]:
    """§6 combat_mechanics.md: проверка в начале хода атакующей стороны.

    Возвращает None, если проверка неприменима (право сгорело или HP выше
    порога) — ход продолжается как обычно без вызова этой функции вообще.
    Иначе — dict с "proceed" (продолжать ли сборку хода в этом же ответе) и
    "text".
    """
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    attacker_role = session.current_turn

    if attacker_role == "player":
        right_used = session.player_flee_right_used
        current_hp, max_hp, luck = session.character_hp_snapshot, pr.calculate_hp_max(character.vitality), character.luck
    else:
        right_used = session.enemy_flee_right_used
        current_hp, max_hp, luck = session.enemy_hp_current, enemy_stats["hp_max"], enemy_stats["luck"]

    if right_used or not cm.is_hp_at_or_below_flee_threshold(current_hp, max_hp):
        return None

    luck_roll = random.randint(1, 10)
    faces = cm.calculate_flee_opportunity_success_faces(luck, FLEE_MAX_FACES, FLEE_K)
    triggered = cm.is_flee_opportunity_triggered(luck_roll, faces)
    check_text = rendering.render_flee_opportunity_check(current_hp, max_hp, luck_roll, triggered)
    log_entry = {"type": "flee_opportunity_check", "side": attacker_role, "roll": luck_roll, "triggered": triggered}

    if not triggered:
        session.turn_log = session.turn_log + [log_entry]
        db.commit()
        return {"proceed": True, "text": check_text}

    if attacker_role == "player":
        # Пауза — ждём отдельного POST /flee_decision (только игрок выбирает).
        session.status = "awaiting_flee_decision"
        session.turn_log = session.turn_log + [log_entry]
        db.commit()
        return {"proceed": False, "text": check_text}

    # §7: бот всегда бежит, если возможность открылась — резолвится синхронно.
    pursuer_strength = character.strength * session.strength_modifier_player
    attack_roll = random.randint(1, 10)
    flee = cm.resolve_flee_attempt(pursuer_strength, attack_roll, current_hp)
    session.enemy_hp_current = flee.fleeing_hp_after
    result = "victory" if flee.fleeing_defeated else "enemy_fled"
    flee_text = rendering.render_flee_attempt(
        session.enemy_type, "enemy", attack_roll, flee.attack_percent, flee.damage, flee.fleeing_defeated
    )
    session.turn_log = session.turn_log + [
        log_entry,
        {
            "type": "flee_attempt",
            "fleeing_role": "enemy",
            "attack_roll": attack_roll,
            "damage": flee.damage,
            "defeated": flee.fleeing_defeated,
        },
    ]
    finish_text = _finish_battle(session, character, result, db)
    db.commit()
    db.refresh(session)
    return {"proceed": False, "text": f"{check_text}\n\n{flee_text}\n\n{finish_text}"}


def _resolve_attacker_turn(session: CombatSession, character: Character, db: Session) -> str:
    """§5+§9 шаги 5-6: проверка двойного удара + 1-2 удара для session.current_turn."""
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    attacker_role = session.current_turn
    defender_role = "enemy" if attacker_role == "player" else "player"

    if attacker_role == "player":
        attacker_strength = character.strength * session.strength_modifier_player
        defender_agility = enemy_stats["agility"]
        attacker_luck = character.luck
    else:
        attacker_strength = enemy_stats["strength"] * session.strength_modifier_enemy
        defender_agility = character.agility
        attacker_luck = enemy_stats["luck"]

    texts = []
    log_entries = []

    ds_faces = cm.calculate_double_strike_success_faces(attacker_luck, DOUBLE_STRIKE_K)
    luck_roll = random.randint(1, 10)
    triggered = cm.is_double_strike_triggered(luck_roll, ds_faces)
    texts.append(rendering.render_double_strike_check(session.enemy_type, attacker_role, luck_roll, triggered))
    log_entries.append({"type": "double_strike_check", "side": attacker_role, "roll": luck_roll, "triggered": triggered})

    battle_ended = False
    result = None
    for strike_number in range(1, (2 if triggered else 1) + 1):
        attack_roll = random.randint(1, 10)
        dodge_roll = random.randint(1, 10)
        strike = cm.resolve_strike(
            attacker_strength=attacker_strength,
            defender_agility=defender_agility,
            attack_roll=attack_roll,
            dodge_roll=dodge_roll,
            dodge_max_faces=DODGE_MAX_FACES,
            dodge_k=DODGE_K,
        )

        if defender_role == "enemy":
            session.enemy_hp_current = max(session.enemy_hp_current - strike.damage, 0)
            defender_hp_after = session.enemy_hp_current
        else:
            session.character_hp_snapshot = max(session.character_hp_snapshot - strike.damage, 0)
            defender_hp_after = session.character_hp_snapshot

        if triggered:
            texts.append(
                rendering.render_compact_strike(
                    session.enemy_type, attacker_role, strike_number, attack_roll,
                    strike.attack_percent, dodge_roll, strike.dodged, strike.damage,
                )
            )
        else:
            texts.append(
                rendering.render_strike(
                    session.enemy_type, attacker_role, attack_roll,
                    strike.attack_percent, dodge_roll, strike.dodged, strike.damage,
                )
            )
        log_entries.append(
            {
                "type": "strike", "side": attacker_role, "strike_number": strike_number,
                "attack_roll": attack_roll, "attack_percent": strike.attack_percent,
                "dodge_roll": dodge_roll, "dodged": strike.dodged, "damage": strike.damage,
            }
        )

        if defender_hp_after <= 0:
            battle_ended = True
            result = "victory" if attacker_role == "player" else "defeat"
            break

    session.turn_log = session.turn_log + log_entries

    if battle_ended:
        texts.append(_finish_battle(session, character, result, db))
    else:
        session.current_turn = defender_role

    db.commit()
    db.refresh(session)
    return "\n\n".join(texts)


@router.post("/combat/{combat_session_id}/confirm", response_model=CombatTurnResponse)
def confirm_combat(
    combat_session_id: int,
    payload: ConfirmRequest,
    character: Character = Depends(get_current_character),
    db: Session = Depends(get_db),
) -> CombatTurnResponse:
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "awaiting_confirmation":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"unexpected session status: {session.status!r}"
        )

    if payload.decision == "fight":
        session.status = "active"
        db.commit()
        db.refresh(session)
        return CombatTurnResponse(
            combat_session_id=session.id, status=session.status, result=None,
            current_turn=session.current_turn, text="⚔️ Ты вступаешь в бой!",
        )

    # §9 шаг 3б / §7: отказ -> безответный удар противника без защиты.
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    pursuer_strength = enemy_stats["strength"] * session.strength_modifier_enemy
    attack_roll = random.randint(1, 10)
    flee = cm.resolve_flee_attempt(pursuer_strength, attack_roll, session.character_hp_snapshot)
    session.character_hp_snapshot = flee.fleeing_hp_after
    result = "defeat" if flee.fleeing_defeated else "player_fled"
    flee_text = rendering.render_flee_attempt(
        session.enemy_type, "player", attack_roll, flee.attack_percent, flee.damage, flee.fleeing_defeated
    )
    session.turn_log = session.turn_log + [
        {
            "type": "flee_attempt", "fleeing_role": "player", "attack_roll": attack_roll,
            "damage": flee.damage, "defeated": flee.fleeing_defeated,
        }
    ]
    finish_text = _finish_battle(session, character, result, db)
    db.commit()
    db.refresh(session)
    return CombatTurnResponse(
        combat_session_id=session.id, status=session.status, result=session.result,
        current_turn=session.current_turn, text=f"{flee_text}\n\n{finish_text}",
    )


@router.post("/combat/{combat_session_id}/turn", response_model=CombatTurnResponse)
def take_turn(
    combat_session_id: int,
    character: Character = Depends(get_current_character),
    db: Session = Depends(get_db),
) -> CombatTurnResponse:
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"unexpected session status: {session.status!r}"
        )

    gate = _check_flee_gate(session, character, db)
    if gate is not None and not gate["proceed"]:
        return CombatTurnResponse(
            combat_session_id=session.id, status=session.status, result=session.result,
            current_turn=session.current_turn, text=gate["text"],
        )

    turn_text = _resolve_attacker_turn(session, character, db)
    if gate is not None:
        turn_text = f"{gate['text']}\n\n{turn_text}"

    return CombatTurnResponse(
        combat_session_id=session.id, status=session.status, result=session.result,
        current_turn=session.current_turn, text=turn_text,
    )


@router.post("/combat/{combat_session_id}/flee_decision", response_model=CombatTurnResponse)
def flee_decision(
    combat_session_id: int,
    payload: FleeDecisionRequest,
    character: Character = Depends(get_current_character),
    db: Session = Depends(get_db),
) -> CombatTurnResponse:
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "awaiting_flee_decision":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"unexpected session status: {session.status!r}"
        )

    attacker_role = session.current_turn  # на практике всегда "player"

    if payload.decision == "flee":
        enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
        pursuer_strength = enemy_stats["strength"] * session.strength_modifier_enemy
        attack_roll = random.randint(1, 10)
        flee = cm.resolve_flee_attempt(pursuer_strength, attack_roll, session.character_hp_snapshot)
        session.character_hp_snapshot = flee.fleeing_hp_after
        result = "defeat" if flee.fleeing_defeated else "player_fled"
        flee_text = rendering.render_flee_attempt(
            session.enemy_type, "player", attack_roll, flee.attack_percent, flee.damage, flee.fleeing_defeated
        )
        session.turn_log = session.turn_log + [
            {
                "type": "flee_attempt", "fleeing_role": "player", "attack_roll": attack_roll,
                "damage": flee.damage, "defeated": flee.fleeing_defeated,
            }
        ]
        finish_text = _finish_battle(session, character, result, db)
        db.commit()
        db.refresh(session)
        return CombatTurnResponse(
            combat_session_id=session.id, status=session.status, result=session.result,
            current_turn=session.current_turn, text=f"{flee_text}\n\n{finish_text}",
        )

    # "continue" — право сгорает, ход доигрывается в этом же ответе (§6).
    if attacker_role == "player":
        session.player_flee_right_used = True
    else:
        session.enemy_flee_right_used = True
    session.status = "active"
    db.commit()

    turn_text = _resolve_attacker_turn(session, character, db)
    return CombatTurnResponse(
        combat_session_id=session.id, status=session.status, result=session.result,
        current_turn=session.current_turn, text=turn_text,
    )


@router.get("/combat/{combat_session_id}", response_model=CombatSessionOut)
def get_combat_session(
    combat_session_id: int,
    character: Character = Depends(get_current_character),
    db: Session = Depends(get_db),
) -> CombatSessionOut:
    session = _load_owned_session(db, combat_session_id, character)
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    return CombatSessionOut(
        combat_session_id=session.id,
        enemy_type=session.enemy_type,
        status=session.status,
        result=session.result,
        current_turn=session.current_turn,
        player_hp_current=session.character_hp_snapshot,
        enemy_hp_current=session.enemy_hp_current,
        enemy_hp_max=enemy_stats["hp_max"],
    )
