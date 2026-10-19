"""Оркестрация хода боя (docs/hardening_plan.md, этап 4, п.3) — композиция
формул core/combat_mechanics.py с состоянием CombatSession, которое core/
намеренно не знает (docs/backend_plan.md §6). Роутер api/routers/combat.py
остаётся тонким: читает/проверяет статус, зовёт функции этого модуля,
сохраняет, возвращает JSON — никакой игровой логики в самом роутере.
"""

import random
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from api import enemy_content, rendering
from core import combat_mechanics as cm
from core import economy as ec
from core import progression as pr
from db.models import Character, CombatSession


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def finish_battle(session: CombatSession, character: Character, result: str, db: Session, rng: random.Random) -> str:
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
        loot_name, _loot_price = ec.resolve_loot_drop(session.enemy_type, rng.randint(1, 100))
        if loot_name != "nothing":
            loot_dropped = loot_name
            character.loot = {**character.loot, loot_name: character.loot.get(loot_name, 0) + 1}

    hp_max = pr.calculate_hp_max(character.vitality)
    seconds_to_full = pr.time_to_full_hp(character.hp_current, hp_max)
    return rendering.render_battle_end(
        session.enemy_type,
        result,
        reward,
        character.victory_points,
        character.hp_current,
        hp_max,
        seconds_to_full,
        loot_dropped=loot_dropped,
    )


def resolve_flee_attempt(
    session: CombatSession,
    character: Character,
    db: Session,
    rng: random.Random,
    *,
    fleeing_role: str,
    pursuer_strength: float,
    fleeing_current_hp: float,
) -> str:
    """§7 combat_mechanics.md: безответный удар преследователя без защиты
    убегающего — общий паттерн для трёх разных поводов попытки побега
    (отказ от боя сразу после обстоятельства — confirm_combat; явный выбор
    "🏃 Сбежать" по HP-порогу — flee_decision; автопобег бота, когда
    возможность открылась у него — check_flee_gate). Раньше был списан в
    каждое из трёх мест почти без изменений.

    `fleeing_role` — "player" | "enemy": чья сторона убегает, определяет и
    какое HP-поле сессии обновлять, и как назвать исход боя. `flee.missed`
    здесь не читается — ни один из трёх старых сайтов его не использовал."""
    attack_roll = rng.randint(1, 10)
    flee = cm.resolve_flee_attempt(pursuer_strength, attack_roll, fleeing_current_hp)

    if fleeing_role == "player":
        session.character_hp_snapshot = flee.fleeing_hp_after
        result = "defeat" if flee.fleeing_defeated else "player_fled"
    else:
        session.enemy_hp_current = flee.fleeing_hp_after
        result = "victory" if flee.fleeing_defeated else "enemy_fled"

    flee_text = rendering.render_flee_attempt(
        session.enemy_type, fleeing_role, attack_roll, flee.attack_percent, flee.damage, flee.fleeing_defeated
    )
    session.turn_log = session.turn_log + [
        {
            "type": "flee_attempt",
            "fleeing_role": fleeing_role,
            "attack_roll": attack_roll,
            "damage": flee.damage,
            "defeated": flee.fleeing_defeated,
        }
    ]
    finish_text = finish_battle(session, character, result, db, rng)
    db.commit()
    db.refresh(session)
    return f"{flee_text}\n\n{finish_text}"


def apply_potion(session: CombatSession, character: Character, size: str, db: Session) -> str:
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
    api/routers/combat.py (_turn_response/use_potion), они читают то же поле
    как есть."""
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


def check_flee_gate(session: CombatSession, character: Character, db: Session, rng: random.Random) -> dict | None:
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
    # current_turn — None только до инициативы (docs/notes.md); эта функция
    # вызывается на ходу атакующей стороны, инициатива уже брошена.
    assert attacker_role is not None

    if attacker_role == "player":
        # Из боя с финальным боссом нельзя сбежать вообще, ни игроку, ни ему
        # самому (docs/notes.md, п.36/п.57) — player_can_flee в content/
        # enemies.json, симметричный флаг к can_flee у стороны enemy ниже.
        if not enemy_stats.get("player_can_flee", True):
            return None
        right_used = session.player_flee_right_used
        current_hp, max_hp, luck = (
            session.character_hp_snapshot,
            pr.calculate_hp_max(character.vitality),
            character.luck,
        )
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

    luck_roll = rng.randint(1, 10)
    faces = cm.calculate_flee_opportunity_success_faces(luck)
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
        hp_status = hp_status_text(session, character, enemy_stats)
        db.commit()
        return {"proceed": False, "text": f"{hp_status}\n\n{check_text}"}

    # §7: бот всегда бежит, если возможность открылась — резолвится синхронно.
    session.turn_log = session.turn_log + [log_entry]
    pursuer_strength = character.strength * session.strength_modifier_player
    attempt_text = resolve_flee_attempt(
        session,
        character,
        db,
        rng,
        fleeing_role="enemy",
        pursuer_strength=pursuer_strength,
        fleeing_current_hp=current_hp,
    )
    return {"proceed": False, "text": f"{check_text}\n\n{attempt_text}"}


def hp_status_text(session: CombatSession, character: Character, enemy_stats: dict) -> str:
    """Шапка HP — печатается первой строкой в каждом сообщении боя (пока бой не завершён)."""
    player_hp_max = pr.calculate_hp_max(character.vitality)
    return rendering.render_hp_status(
        session.enemy_type,
        session.character_hp_snapshot,
        player_hp_max,
        session.enemy_hp_current,
        enemy_stats["hp_max"],
    )


def render_resume_text(session: CombatSession, character: Character) -> str:
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
            session.enemy_type,
            initiative_entry["player_roll"],
            initiative_entry["enemy_roll"],
            initiative_entry["first_role"],
        )
        # Босс без обстоятельства (docs/notes.md, п.56 — has_circumstance=false
        # в content/enemies.json) — нет и записи в turn_log, реконструировать нечего.
        circumstance_entry = next((e for e in session.turn_log if e["type"] == "circumstance"), None)
        if circumstance_entry is None:
            return initiative_text
        circumstance_text = rendering.render_circumstance(
            session.enemy_type,
            circumstance_entry["roll"],
            circumstance_entry["outcome"],
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
            session.enemy_type,
            check_entry["side"],
            current_hp,
            max_hp,
            check_entry["roll"],
            check_entry["triggered"],
        )
        return f"{hp_status_text(session, character, enemy_stats)}\n\n{check_text}"

    # "active" — обычный случай; любой другой (например, "finished", сюда
    # не должен попасть — эндпоинт вызывается только для незавершённых
    # сессий) — тоже просто статус HP, безопасный дефолт.
    return hp_status_text(session, character, enemy_stats)


def resolve_attacker_turn(
    session: CombatSession, character: Character, db: Session, rng: random.Random, power_attack: bool = False
) -> str:
    """§5+§9 шаги 5-6: проверка двойного удара + 1-2 удара для session.current_turn.

    power_attack (docs/combat_mechanics.md §3a) — выбор игрока, передаётся
    сюда как есть из запроса, но реально применяется только когда атакующая
    сторона в этом ходу — игрок (см. ниже); бот всегда бьёт обычной атакой,
    как и должно быть по механике."""
    enemy_stats = enemy_content.get_enemy_stats(session.enemy_type)
    attacker_role = session.current_turn
    # current_turn — None только до инициативы (docs/notes.md); эта функция
    # вызывается на реальном ходу, инициатива уже брошена.
    assert attacker_role is not None
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

    texts: list[str] = []
    log_entries: list[dict[str, Any]] = []

    ds_faces = cm.calculate_double_strike_success_faces(attacker_luck)
    luck_roll = rng.randint(1, 10)
    triggered = cm.is_double_strike_triggered(luck_roll, ds_faces)
    texts.append(rendering.render_double_strike_check(session.enemy_type, attacker_role, luck_roll, triggered))
    log_entries.append(
        {"type": "double_strike_check", "side": attacker_role, "roll": luck_roll, "triggered": triggered}
    )

    battle_ended = False
    result = None
    for strike_number in range(1, (2 if triggered else 1) + 1):
        attack_roll = rng.randint(1, 10)
        dodge_roll = rng.randint(1, 10)
        strike = cm.resolve_strike(
            attacker_strength=attacker_strength,
            defender_agility=defender_agility,
            attack_roll=attack_roll,
            dodge_roll=dodge_roll,
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
                    session.enemy_type,
                    attacker_role,
                    strike_number,
                    attack_roll,
                    strike.attack_percent,
                    dodge_roll,
                    strike.dodged,
                    strike.damage,
                    power_attack=power_attack,
                )
            )
        else:
            texts.append(
                rendering.render_strike(
                    session.enemy_type,
                    attacker_role,
                    attack_roll,
                    strike.attack_percent,
                    dodge_roll,
                    strike.dodged,
                    strike.damage,
                    power_attack=power_attack,
                )
            )
        log_entries.append(
            {
                "type": "strike",
                "side": attacker_role,
                "strike_number": strike_number,
                "attack_roll": attack_roll,
                "attack_percent": strike.attack_percent,
                "dodge_roll": dodge_roll,
                "dodged": strike.dodged,
                "damage": strike.damage,
                "power_attack": power_attack,
            }
        )

        if defender_hp_after <= 0:
            battle_ended = True
            result = "victory" if attacker_role == "player" else "defeat"
            break

    session.turn_log = session.turn_log + log_entries

    if battle_ended:
        # battle_ended устанавливается в True в той же ветке, что и result
        # (строки выше) — mypy не связывает две разные переменные, но
        # инвариант реальный: result не None именно тогда, когда battle_ended.
        assert result is not None
        texts.append(finish_battle(session, character, result, db, rng))
    else:
        session.current_turn = defender_role

    db.commit()
    db.refresh(session)
    return "\n\n".join(texts)
