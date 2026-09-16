"""Роутеры для начала боя: поиск противника + запуск инициативы/обстоятельства.

Разбито на два HTTP-запроса, а не один (в отличие от чернового наброска в
backend_plan.md §5), чтобы соответствовать двум отдельным нажатиям кнопок в
gameplay_loop_mvp.md §9 ("Искать противника" -> "Определить инициативу") и
принципу "один HTTP-запрос = один шаг".
"""

import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api import enemy_content
from api import rendering
from api.dependencies import get_current_character, get_db, require_api_key
from api.schemas.combat import CombatStartResponse, EncounterSearchResponse
from core import combat_mechanics as cm
from core import progression as pr
from db.models import Character, CombatSession

router = APIRouter(tags=["encounter", "combat"], dependencies=[Depends(require_api_key)])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _roll_enemy_encounter(level: int) -> tuple:
    """§6 gameplay_loop_mvp.md: d10, грани по pr.calculate_encounter_faces(level)
    — на 1 уровне 50/30/20 (мышь/волк/кабан), к позднему уровню зеркально
    20/30/50 (пересмотрено 2026-09-16, было фиксировано на всех уровнях)."""
    mouse_faces, wolf_faces, _boar_faces = pr.calculate_encounter_faces(level)
    roll = random.randint(1, 10)
    if roll <= mouse_faces:
        return roll, "mouse"
    if roll <= mouse_faces + wolf_faces:
        return roll, "wolf"
    return roll, "boar"


def _circumstance_multiplier(outcome) -> float:
    if outcome == "buff":
        return 1 + cm.CIRCUMSTANCE_MODIFIER_PERCENT_DEFAULT / 100
    if outcome == "debuff":
        return 1 - cm.CIRCUMSTANCE_MODIFIER_PERCENT_DEFAULT / 100
    return 1.0


@router.post("/encounter/search", response_model=EncounterSearchResponse)
def search_encounter(
    character: Character = Depends(get_current_character),
    db: Session = Depends(get_db),
) -> EncounterSearchResponse:
    active_session = (
        db.query(CombatSession)
        .filter(CombatSession.character_id == character.id, CombatSession.status != "finished")
        .first()
    )
    if active_session is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="character already has an active combat session"
        )

    roll, enemy_type = _roll_enemy_encounter(character.level)
    enemy_stats = enemy_content.get_enemy_stats(enemy_type)

    # Снимок HP на начало боя — та же точка, где регенерация обычно
    # пересчитывается лениво (§8 gameplay_loop_mvp.md), но здесь результат
    # сразу же фиксируется в БД: дальше HP персонажа "живёт" внутри боя, а не
    # регенерирует по времени, пока сессия активна.
    now = _now()
    hp_max = pr.calculate_hp_max(character.vitality)
    hp_current = pr.get_current_hp(character.hp_current, hp_max, character.last_hp_update_at, now)
    character.hp_current = hp_current
    character.last_hp_update_at = now

    session = CombatSession(
        character_id=character.id,
        enemy_type=enemy_type,
        enemy_hp_current=enemy_stats["hp_max"],
        character_hp_snapshot=hp_current,
        current_turn=None,
        status="awaiting_initiative",
        turn_log=[{"type": "encounter", "roll": roll, "enemy_type": enemy_type}],
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return EncounterSearchResponse(
        combat_session_id=session.id,
        enemy_type=enemy_type,
        status=session.status,
        text=rendering.render_encounter(enemy_type, roll),
    )


@router.post("/combat/{combat_session_id}/start", response_model=CombatStartResponse)
def start_combat(
    combat_session_id: int,
    character: Character = Depends(get_current_character),
    db: Session = Depends(get_db),
) -> CombatStartResponse:
    session = db.get(CombatSession, combat_session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="combat session not found")
    if session.character_id != character.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your combat session")
    if session.status != "awaiting_initiative":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"unexpected session status: {session.status!r}"
        )

    while True:
        player_roll = random.randint(1, 10)
        enemy_roll = random.randint(1, 10)
        initiative = cm.resolve_initiative(player_roll, enemy_roll)
        if initiative is not None:
            break
    first_role = "player" if initiative == "first" else "enemy"

    circumstance_roll = random.randint(1, 10)
    circumstance_outcome = cm.resolve_circumstance_outcome(circumstance_roll)
    multiplier = _circumstance_multiplier(circumstance_outcome)
    roller_role = first_role  # §8: кидает победитель инициативы

    player_modifier = multiplier if roller_role == "player" else 1.0
    enemy_modifier = multiplier if roller_role == "enemy" else 1.0

    session.current_turn = first_role
    session.status = "awaiting_confirmation"
    session.circumstance_outcome = circumstance_outcome
    session.circumstance_roller = roller_role
    session.strength_modifier_player = player_modifier
    session.strength_modifier_enemy = enemy_modifier
    session.turn_log = session.turn_log + [
        {"type": "initiative", "player_roll": player_roll, "enemy_roll": enemy_roll, "first_role": first_role},
        {"type": "circumstance", "roll": circumstance_roll, "outcome": circumstance_outcome, "roller_role": roller_role},
    ]
    db.commit()
    db.refresh(session)

    initiative_text = rendering.render_initiative(session.enemy_type, player_roll, enemy_roll, first_role)
    circumstance_text = rendering.render_circumstance(
        session.enemy_type, circumstance_roll, circumstance_outcome, roller_role
    )

    return CombatStartResponse(
        combat_session_id=session.id,
        status=session.status,
        first_role=first_role,
        player_strength_modifier=player_modifier,
        enemy_strength_modifier=enemy_modifier,
        text=f"{initiative_text}\n\n{circumstance_text}",
    )
