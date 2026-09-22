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
    TurnRequest,
    UsePotionRequest,
)
from core import combat_mechanics as cm
from core import economy as ec
from core import progression as pr
from db.models import Character, CombatSession

router = APIRouter(tags=["combat"], dependencies=[Depends(require_api_key)])

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
    """§10 combat_mechanics.md: применить исход — награда, уровни, синхронизация HP.

    Лут (docs/notes.md, п.30) — независимый бросок ПОСЛЕ исхода, только при
    victory, как и в симуляторе/core.economy.resolve_loot_drop: накапливается
    в character.loot (не авто-продаётся) — продажа отдельным нажатием
    "Продать весь лут" на экране "Меню игрока".

    Победа над финальным боссом (docs/notes.md, п.36/п.54) — конец игры, не
    обычный исход: своя ранняя ветка, без награды/уровней/лута/синхронизации
    HP вообще — ничего из этого не нужно, персонаж дальше только обнуляется
    нажатием "Начать заново"."""
    if session.enemy_type == "boss" and result == "victory":
        session.status = "finished"
        session.result = result
        return rendering.render_boss_victory()

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

    loot_dropped = None
    if result == "victory":
        loot_name, _loot_price = ec.resolve_loot_drop(session.enemy_type, random.randint(1, 100))
        if loot_name != "nothing":
            loot_dropped = loot_name
            character.loot = {**character.loot, loot_name: character.loot.get(loot_name, 0) + 1}

    hp_max = pr.calculate_hp_max(character.vitality)
    seconds_to_full = pr.time_to_full_hp(character.hp_current, hp_max)
    return rendering.render_battle_end(
        session.enemy_type, result, reward, character.victory_points, character.hp_current, hp_max,
        seconds_to_full, loot_dropped=loot_dropped,
    )


def _use_potion(session: CombatSession, character: Character, size: str, db: Session) -> str:
    """Зелье — явное действие игрока в свой ход, кнопкой (docs/notes.md,
    п.33 — отменяет автоматику по порогу HP из п.32: та срабатывала и в
    автобою/"показать результат", где игрок ничего не выбирает, а зелье
    должно быть только ручным решением). Использование ЗАМЕНЯЕТ атаку в
    этот ход, а не бесплатное дополнение к ней — сразу передаёт ход
    противнику, как и обычный удар (§9 шаг 7). Лимит — общий на оба
    размера, раз за бой (player_potion_used_this_battle — то же поле, что
    и в п.32, семантика лимита не изменилась, изменился только триггер).
    core.economy.calculate_heal_amount переиспользуется как есть.

    Исключение — противник с unlimited_potions (сейчас только босс,
    content/enemies.json, docs/notes.md п.39): флаг лимита не выставляется
    вообще, тем же принципом, что и can_flee у побега — единственный
    источник правды, не нужно ничего "маскировать" на выходе в
    _turn_response/use_potion, они читают то же поле как есть."""
    hp_max = pr.calculate_hp_max(character.vitality)
    heal = ec.calculate_heal_amount(hp_max, size)
    session.character_hp_snapshot = min(session.character_hp_snapshot + heal, hp_max)
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    if not enemy_stats.get("unlimited_potions", False):
        session.player_potion_used_this_battle = True
    if size == "large":
        character.potions_large -= 1
    else:
        character.potions_small -= 1
    session.turn_log = session.turn_log + [{"type": "potion_used", "size": size, "heal": heal}]
    session.current_turn = "enemy"
    db.commit()
    db.refresh(session)
    return rendering.render_potion_used(size, heal)


def _check_flee_gate(session: CombatSession, character: Character, db: Session) -> Optional[dict]:
    """§6 combat_mechanics.md: проверка в начале хода атакующей стороны.

    Одна попытка за бой на сторону (docs/notes.md, п.9) — право сгорает
    сразу после броска, независимо от исхода, не только при отказе после
    успеха. Возвращает None, если проверка неприменима (право уже
    использовано или HP выше порога) — ход продолжается как обычно без
    вызова этой функции вообще. Иначе — dict с "proceed" (продолжать ли
    сборку хода в этом же ответе) и "text".
    """
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    attacker_role = session.current_turn

    if attacker_role == "player":
        # Из боя с финальным боссом нельзя сбежать вообще, ни игроку, ни ему
        # самому (docs/notes.md, п.36/п.57) — player_can_flee в content/
        # enemies.json, симметричный флаг к can_flee у стороны enemy ниже.
        if not enemy_stats.get("player_can_flee", True):
            return None
        right_used = session.player_flee_right_used
        current_hp, max_hp, luck = session.character_hp_snapshot, pr.calculate_hp_max(character.vitality), character.luck
    else:
        # Финальный босс бьётся до конца (docs/notes.md, п.36) — can_flee в
        # content/enemies.json, не хардкод по названию.
        if not enemy_stats.get("can_flee", True):
            return None
        right_used = session.enemy_flee_right_used
        current_hp, max_hp, luck = session.enemy_hp_current, enemy_stats["hp_max"], enemy_stats["luck"]

    if right_used or not cm.is_hp_at_or_below_flee_threshold(current_hp, max_hp):
        return None

    if attacker_role == "player":
        session.player_flee_right_used = True
    else:
        session.enemy_flee_right_used = True

    luck_roll = random.randint(1, 10)
    faces = cm.calculate_flee_opportunity_success_faces(luck, FLEE_MAX_FACES, FLEE_K)
    triggered = cm.is_flee_opportunity_triggered(luck_roll, faces)
    check_text = rendering.render_flee_opportunity_check(
        session.enemy_type, attacker_role, current_hp, max_hp, luck_roll, triggered
    )
    log_entry = {"type": "flee_opportunity_check", "side": attacker_role, "roll": luck_roll, "triggered": triggered}

    if not triggered:
        session.turn_log = session.turn_log + [log_entry]
        db.commit()
        return {"proceed": True, "text": check_text}

    if attacker_role == "player":
        # Пауза — ждём отдельного POST /flee_decision (только игрок выбирает).
        session.status = "awaiting_flee_decision"
        session.turn_log = session.turn_log + [log_entry]
        hp_status = _hp_status_text(session, character, enemy_stats)
        db.commit()
        return {"proceed": False, "text": f"{hp_status}\n\n{check_text}"}

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


def _hp_status_text(session: CombatSession, character: Character, enemy_stats: dict) -> str:
    """Шапка HP — печатается первой строкой в каждом сообщении боя (пока бой не завершён)."""
    player_hp_max = pr.calculate_hp_max(character.vitality)
    return rendering.render_hp_status(
        session.enemy_type, session.character_hp_snapshot, player_hp_max,
        session.enemy_hp_current, enemy_stats["hp_max"],
    )


def _render_resume_text(session: CombatSession, character: Character) -> str:
    """Реконструирует экран боя по текущему status, когда клавиатура на
    стороне бота потеряна (docs/notes.md, п.48 — например, игрок удалил
    чат в Telegram: CombatSession в БД остаётся как есть, бой никуда не
    делся, просто бот не показывает сообщение с кнопками для него нигде).
    Только чтение — ничего не бросает заново, восстанавливает текст по уже
    сохранённым фактам (turn_log/колонки сессии), не по свежим roll'ам."""
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)

    if session.status == "awaiting_initiative":
        encounter_entry = session.turn_log[0]
        if "roll" in encounter_entry:
            return rendering.render_encounter(session.enemy_type, encounter_entry["roll"])
        return rendering.render_boss_encounter()

    if session.status == "awaiting_confirmation":
        initiative_entry = next(e for e in session.turn_log if e["type"] == "initiative")
        initiative_text = rendering.render_initiative(
            session.enemy_type, initiative_entry["player_roll"], initiative_entry["enemy_roll"],
            initiative_entry["first_role"],
        )
        # Босс без обстоятельства (docs/notes.md, п.56 — has_circumstance=false
        # в content/enemies.json) — нет и записи в turn_log, реконструировать нечего.
        circumstance_entry = next((e for e in session.turn_log if e["type"] == "circumstance"), None)
        if circumstance_entry is None:
            return initiative_text
        circumstance_text = rendering.render_circumstance(
            session.enemy_type, circumstance_entry["roll"], circumstance_entry["outcome"],
            circumstance_entry["roller_role"],
        )
        return f"{initiative_text}\n\n{circumstance_text}"

    if session.status == "awaiting_flee_decision":
        check_entry = next(e for e in reversed(session.turn_log) if e["type"] == "flee_opportunity_check")
        if check_entry["side"] == "player":
            current_hp, max_hp = session.character_hp_snapshot, pr.calculate_hp_max(character.vitality)
        else:
            current_hp, max_hp = session.enemy_hp_current, enemy_stats["hp_max"]
        check_text = rendering.render_flee_opportunity_check(
            session.enemy_type, check_entry["side"], current_hp, max_hp, check_entry["roll"], check_entry["triggered"],
        )
        return f"{_hp_status_text(session, character, enemy_stats)}\n\n{check_text}"

    # "active" — обычный случай; любой другой (например, "finished", сюда
    # не должен попасть — эндпоинт вызывается только для незавершённых
    # сессий) — тоже просто статус HP, безопасный дефолт.
    return _hp_status_text(session, character, enemy_stats)


def _turn_response(session: CombatSession, character: Character, text: str) -> CombatTurnResponse:
    """Снимок инвентаря зелий игрока (docs/notes.md, п.33) — бот решает по
    нему, показывать ли кнопку "Выпить зелье" на следующем ходу, без
    отдельного вызова get_character на каждом шаге."""
    return CombatTurnResponse(
        combat_session_id=session.id, status=session.status, result=session.result,
        current_turn=session.current_turn, enemy_type=session.enemy_type, text=text,
        potions_small=character.potions_small, potions_large=character.potions_large,
        potion_used_this_battle=session.player_potion_used_this_battle,
    )


def _resolve_attacker_turn(
    session: CombatSession, character: Character, db: Session, power_attack: bool = False
) -> str:
    """§5+§9 шаги 5-6: проверка двойного удара + 1-2 удара для session.current_turn.

    power_attack (docs/combat_mechanics.md §3a) — выбор игрока, передаётся
    сюда как есть из запроса, но реально применяется только когда атакующая
    сторона в этом ходу — игрок (см. ниже); бот всегда бьёт обычной атакой,
    как и должно быть по механике."""
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    attacker_role = session.current_turn
    defender_role = "enemy" if attacker_role == "player" else "player"
    power_attack = power_attack and attacker_role == "player"

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
            dodge_k=DODGE_K,
            power_attack=power_attack,
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
                    power_attack=power_attack,
                )
            )
        else:
            texts.append(
                rendering.render_strike(
                    session.enemy_type, attacker_role, attack_roll,
                    strike.attack_percent, dodge_roll, strike.dodged, strike.damage,
                    power_attack=power_attack,
                )
            )
        log_entries.append(
            {
                "type": "strike", "side": attacker_role, "strike_number": strike_number,
                "attack_roll": attack_roll, "attack_percent": strike.attack_percent,
                "dodge_roll": dodge_roll, "dodged": strike.dodged, "damage": strike.damage,
                "power_attack": power_attack,
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
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)

    if payload.decision == "fight":
        session.status = "active"
        hp_status = _hp_status_text(session, character, enemy_stats)
        db.commit()
        db.refresh(session)
        return _turn_response(session, character, f"{hp_status}\n\n⚔️ Ты вступаешь в бой!")

    # Финальный босс — без пути назад после инициативы вообще (docs/notes.md,
    # п.57, player_can_flee=false в content/enemies.json): кнопка "Отступить"
    # у бота для него и так не показывается (_confirmation_keyboard), это —
    # защита от гонки/устаревшей клавиатуры, тот же принцип, что и везде
    # здесь ("клиенту не доверяем").
    if not enemy_stats.get("player_can_flee", True):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="flee_not_allowed")

    # §9 шаг 3б / §7: отказ -> безответный удар противника без защиты.
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
    return _turn_response(session, character, f"{flee_text}\n\n{finish_text}")


@router.post("/combat/{combat_session_id}/turn", response_model=CombatTurnResponse)
def take_turn(
    combat_session_id: int,
    payload: TurnRequest = TurnRequest(),
    character: Character = Depends(get_current_character),
    db: Session = Depends(get_db),
) -> CombatTurnResponse:
    """payload.power_attack (docs/combat_mechanics.md §3a) — по умолчанию
    False, тело запроса необязательно (бот отправляет его всегда, но
    старые/прочие клиенты без тела не ломаются)."""
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"unexpected session status: {session.status!r}"
        )

    gate = _check_flee_gate(session, character, db)
    if gate is not None and not gate["proceed"]:
        return _turn_response(session, character, gate["text"])

    turn_text = _resolve_attacker_turn(session, character, db, power_attack=payload.power_attack)
    if gate is not None:
        turn_text = f"{gate['text']}\n\n{turn_text}"

    if session.status != "finished":
        enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
        turn_text = f"{_hp_status_text(session, character, enemy_stats)}\n\n{turn_text}"

    return _turn_response(session, character, turn_text)


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
        return _turn_response(session, character, f"{flee_text}\n\n{finish_text}")

    # "continue" — право уже сгорело в _check_flee_gate() при самом броске;
    # присвоение здесь избыточно, но безвредно — оставлено для ясности.
    # Ход доигрывается в этом же ответе (§6).
    if attacker_role == "player":
        session.player_flee_right_used = True
    else:
        session.enemy_flee_right_used = True
    session.status = "active"
    db.commit()

    turn_text = _resolve_attacker_turn(session, character, db)
    if session.status != "finished":
        enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
        turn_text = f"{_hp_status_text(session, character, enemy_stats)}\n\n{turn_text}"

    return _turn_response(session, character, turn_text)


@router.post("/combat/{combat_session_id}/use_potion", response_model=CombatTurnResponse)
def use_potion(
    combat_session_id: int,
    payload: UsePotionRequest,
    character: Character = Depends(get_current_character),
    db: Session = Depends(get_db),
) -> CombatTurnResponse:
    """docs/notes.md, п.33 — явное действие игрока в свой ход, не автоматика.
    Заменяет атаку на этот ход (см. _use_potion). Недоступно во время паузы
    "сбежать/биться дальше" (status != "active" -> 409) и не на ходу
    противника (current_turn != "player" -> 409) — кнопка на стороне бота и
    так не показывается в этих случаях, проверка здесь на случай гонки
    (например, два быстрых нажатия подряд)."""
    session = _load_owned_session(db, combat_session_id, character)
    if session.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"unexpected session status: {session.status!r}"
        )
    if session.current_turn != "player":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not your turn")
    if session.player_potion_used_this_battle:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="already_used")

    owned = character.potions_large if payload.size == "large" else character.potions_small
    if owned <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="not_owned")

    potion_text = _use_potion(session, character, payload.size, db)
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    text = f"{_hp_status_text(session, character, enemy_stats)}\n\n{potion_text}"
    return _turn_response(session, character, text)


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


@router.get("/combat/{combat_session_id}/resume", response_model=CombatTurnResponse)
def resume_combat_session(
    combat_session_id: int,
    character: Character = Depends(get_current_character),
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="combat session already finished")
    text = _render_resume_text(session, character)
    return _turn_response(session, character, text)


@router.delete("/combat/{combat_session_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_combat_session(
    combat_session_id: int,
    character: Character = Depends(get_current_character),
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"unexpected session status: {session.status!r}"
        )
    db.delete(session)
    db.commit()
