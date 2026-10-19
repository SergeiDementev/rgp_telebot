"""Роутер /combat — confirm/turn/flee_decision/get: цикл ходов боя (§9 шаги 3-7).

Один HTTP-запрос = один шаг. `/turn` резолвит ровно один ход — чей бы он ни
был (игрока или бота): backend_plan.md §5 описывает это как "ход игрока
(+ автоматически ход бота, если следующая очередь его)" — это значит "если
сейчас очередь бота, его ход резолвится без доп. ввода", а не "всегда два
хода за раз". Кнопки "Атаковать"/"Защищаться" в gameplay_loop_mvp.md §9 —
косметика на стороне бота: обе дёргают один и тот же /turn, подпись бот
выбирает сам по `current_turn` из предыдущего ответа.

Сам цикл хода (двойной удар, удары, побег, завершение боя) — не здесь, а в
api/services/combat.py (docs/hardening_plan.md, этап 4, п.3): роутер только
проверяет статус сессии, зовёт сервис, сохраняет, возвращает JSON.
"""

import random

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from api import enemy_content, rendering
from api.dependencies import get_db, get_localized_character, get_rng, require_api_key
from api.errors import GameError
from api.schemas.combat import (
    CombatSessionOut,
    CombatTurnResponse,
    ConfirmRequest,
    FleeDecisionRequest,
    TurnRequest,
    UsePotionRequest,
)
from api.services import combat as combat_service
from db.models import Character, CombatSession

router = APIRouter(tags=["combat"], dependencies=[Depends(require_api_key)])


def _load_owned_session(db: Session, combat_session_id: int, character: Character) -> CombatSession:
    session = db.get(CombatSession, combat_session_id)
    if session is None:
        raise GameError(status.HTTP_404_NOT_FOUND, "combat.not_found")
    if session.character_id != character.id:
        raise GameError(status.HTTP_403_FORBIDDEN, "combat.not_your_session")
    return session


def _turn_response(session: CombatSession, character: Character, text: str) -> CombatTurnResponse:
    """Снимок инвентаря зелий игрока (docs/notes.md, п.33) — бот решает по
    нему, показывать ли кнопку "Выпить зелье" на следующем ходу, без
    отдельного вызова get_character на каждом шаге."""
    return CombatTurnResponse(
        combat_session_id=session.id,
        status=session.status,
        result=session.result,
        current_turn=session.current_turn,
        enemy_type=session.enemy_type,
        text=text,
        potions_small=character.potions_small,
        potions_large=character.potions_large,
        potion_used_this_battle=session.player_potion_used_this_battle,
        language=character.language,
    )


@router.post("/combat/{combat_session_id}/confirm", response_model=CombatTurnResponse)
def confirm_combat(
    combat_session_id: int,
    payload: ConfirmRequest,
    character: Character = Depends(get_localized_character),
    db: Session = Depends(get_db),
    rng: random.Random = Depends(get_rng),
) -> CombatTurnResponse:
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "awaiting_confirmation":
        raise GameError(status.HTTP_409_CONFLICT, "combat.unexpected_status", {"status": session.status})
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)

    if payload.decision == "fight":
        session.status = "active"
        hp_status = combat_service.hp_status_text(session, character, enemy_stats)
        db.commit()
        db.refresh(session)
        return _turn_response(session, character, f"{hp_status}\n\n{rendering.render_fight_confirmed()}")

    # Финальный босс — без пути назад после инициативы вообще (docs/notes.md,
    # п.57, player_can_flee=false в content/enemies.json): кнопка "Отступить"
    # у бота для него и так не показывается (_confirmation_keyboard), это —
    # защита от гонки/устаревшей клавиатуры, тот же принцип, что и везде
    # здесь ("клиенту не доверяем").
    if not enemy_stats.get("player_can_flee", True):
        raise GameError(status.HTTP_400_BAD_REQUEST, "combat.flee_not_allowed")

    # §9 шаг 3б / §7: отказ -> безответный удар противника без защиты.
    pursuer_strength = enemy_stats["strength"] * session.strength_modifier_enemy
    attempt_text = combat_service.resolve_flee_attempt(
        session,
        character,
        db,
        rng,
        fleeing_role="player",
        pursuer_strength=pursuer_strength,
        fleeing_current_hp=session.character_hp_snapshot,
    )
    return _turn_response(session, character, attempt_text)


@router.post("/combat/{combat_session_id}/turn", response_model=CombatTurnResponse)
def take_turn(
    combat_session_id: int,
    payload: TurnRequest = TurnRequest(),
    character: Character = Depends(get_localized_character),
    db: Session = Depends(get_db),
    rng: random.Random = Depends(get_rng),
) -> CombatTurnResponse:
    """payload.power_attack (docs/combat_mechanics.md §3a) — по умолчанию
    False, тело запроса необязательно (бот отправляет его всегда, но
    старые/прочие клиенты без тела не ломаются)."""
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "active":
        raise GameError(status.HTTP_409_CONFLICT, "combat.unexpected_status", {"status": session.status})

    gate = combat_service.check_flee_gate(session, character, db, rng)
    if gate is not None and not gate["proceed"]:
        return _turn_response(session, character, gate["text"])

    turn_text = combat_service.resolve_attacker_turn(session, character, db, rng, power_attack=payload.power_attack)
    if gate is not None:
        turn_text = f"{gate['text']}\n\n{turn_text}"

    if session.status != "finished":
        enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
        turn_text = f"{combat_service.hp_status_text(session, character, enemy_stats)}\n\n{turn_text}"

    return _turn_response(session, character, turn_text)


@router.post("/combat/{combat_session_id}/flee_decision", response_model=CombatTurnResponse)
def flee_decision(
    combat_session_id: int,
    payload: FleeDecisionRequest,
    character: Character = Depends(get_localized_character),
    db: Session = Depends(get_db),
    rng: random.Random = Depends(get_rng),
) -> CombatTurnResponse:
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "awaiting_flee_decision":
        raise GameError(status.HTTP_409_CONFLICT, "combat.unexpected_status", {"status": session.status})

    attacker_role = session.current_turn  # на практике всегда "player"

    if payload.decision == "flee":
        enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
        pursuer_strength = enemy_stats["strength"] * session.strength_modifier_enemy
        attempt_text = combat_service.resolve_flee_attempt(
            session,
            character,
            db,
            rng,
            fleeing_role="player",
            pursuer_strength=pursuer_strength,
            fleeing_current_hp=session.character_hp_snapshot,
        )
        return _turn_response(session, character, attempt_text)

    # "continue" — право уже сгорело в check_flee_gate() при самом броске;
    # присвоение здесь избыточно, но безвредно — оставлено для ясности.
    # Ход доигрывается в этом же ответе (§6).
    if attacker_role == "player":
        session.player_flee_right_used = True
    else:
        session.enemy_flee_right_used = True
    session.status = "active"
    db.commit()

    turn_text = combat_service.resolve_attacker_turn(session, character, db, rng)
    if session.status != "finished":
        enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
        turn_text = f"{combat_service.hp_status_text(session, character, enemy_stats)}\n\n{turn_text}"

    return _turn_response(session, character, turn_text)


@router.post("/combat/{combat_session_id}/use_potion", response_model=CombatTurnResponse)
def use_potion(
    combat_session_id: int,
    payload: UsePotionRequest,
    character: Character = Depends(get_localized_character),
    db: Session = Depends(get_db),
) -> CombatTurnResponse:
    """docs/notes.md, п.33 — явное действие игрока в свой ход, не автоматика.
    Заменяет атаку на этот ход (см. api.services.combat.apply_potion).
    Недоступно во время паузы "сбежать/биться дальше" (status != "active" ->
    409) и не на ходу противника (current_turn != "player" -> 409) — кнопка
    на стороне бота и так не показывается в этих случаях, проверка здесь на
    случай гонки (например, два быстрых нажатия подряд)."""
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "active":
        raise GameError(status.HTTP_409_CONFLICT, "combat.unexpected_status", {"status": session.status})
    if session.current_turn != "player":
        raise GameError(status.HTTP_409_CONFLICT, "combat.not_your_turn")
    if session.player_potion_used_this_battle:
        raise GameError(status.HTTP_400_BAD_REQUEST, "combat.potion_already_used")

    owned = character.potions_large if payload.size == "large" else character.potions_small
    if owned <= 0:
        raise GameError(status.HTTP_400_BAD_REQUEST, "combat.potion_not_owned")

    potion_text = combat_service.apply_potion(session, character, payload.size, db)
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    text = f"{combat_service.hp_status_text(session, character, enemy_stats)}\n\n{potion_text}"
    return _turn_response(session, character, text)


@router.get("/combat/{combat_session_id}", response_model=CombatSessionOut)
def get_combat_session(
    combat_session_id: int,
    character: Character = Depends(get_localized_character),
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
        language=character.language,
    )


@router.get("/combat/{combat_session_id}/resume", response_model=CombatTurnResponse)
def resume_combat_session(
    combat_session_id: int,
    character: Character = Depends(get_localized_character),
    db: Session = Depends(get_db),
) -> CombatTurnResponse:
    """Восстановление экрана боя, когда клавиатура на стороне бота потеряна
    (docs/notes.md, п.48) — например, игрок удалил чат в Telegram: сама
    CombatSession в БД остаётся активной, бой никуда не делся, просто нет
    сообщения с кнопками, которое вело бы обратно в него. Только чтение —
    не мутирует состояние сессии, никаких новых бросков. Схема ответа та
    же, что и у /confirm//turn/flee_decision/use_potion (CombatTurnResponse)
    — бот переиспользует ту же логику выбора клавиатуры для статусов
    "active"/"awaiting_flee_decision", что и для обычных ответов хода."""
    session = _load_owned_session(db, combat_session_id, character)
    if session.status == "finished":
        raise GameError(status.HTTP_409_CONFLICT, "combat.already_finished")
    text = combat_service.render_resume_text(session, character)
    return _turn_response(session, character, text)


@router.delete("/combat/{combat_session_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_combat_session(
    combat_session_id: int,
    character: Character = Depends(get_localized_character),
    db: Session = Depends(get_db),
) -> None:
    """Отмена встречи ДО инициативы (docs/notes.md, п.51) — кнопка "⬅️ Назад"
    на экране входа в бой ("Ты наткнулся на..."/"Ты входишь в чертог
    Короля"). Разрешено только пока status="awaiting_initiative": до этого
    момента в бою ничего ещё не произошло — ни одного броска инициативы
    /обстоятельства, HP персонажа не тронут (снимок в search снят, но не
    потрачен ни на что) — поэтому просто удаляем сессию физически, не
    архивируем как исход боя (victory/defeat/...), она им и не была."""
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "awaiting_initiative":
        raise GameError(status.HTTP_409_CONFLICT, "combat.unexpected_status", {"status": session.status})
    db.delete(session)
    db.commit()
