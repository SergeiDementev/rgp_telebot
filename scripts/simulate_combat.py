"""Консольный симулятор боёв для калибровки статов противников и констант
формул (docs/combat_mechanics.md, docs/backend_plan.md §8 этап 2).

Не использует БД/HTTP — статы заданы прямо здесь как редактируемые структуры
(этот скрипт ГОТОВИТ content/enemies.json, а не читает его). Бросает кубики
сам (через `random`) и передаёт готовые числа в чистые функции core/ — как и
задумано архитектурой: core/ не содержит случайности, весь orchestration-слой
(здесь — скрипт, в бою — api/) отвечает за броски.

Ориентиры для ручной калибровки по итогам прогона (не зашиты в код):
  - мышь: % побед игрока должен быть очень высоким (~90%+), бой короткий;
  - волк: % побед заметно ниже, ощутимый риск, бой длиннее;
  - кабан: рискованный бой, но не гарантированное поражение.

Запуск:
    python scripts/simulate_combat.py --enemy all --fights 1000 --seed 42
"""

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # Windows-консоль по умолчанию не в UTF-8 — иначе кириллица ломается.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")  # сюда же уходят ошибки argparse
except AttributeError:
    pass

from core import combat_mechanics as cm  # noqa: E402
from core import progression as pr  # noqa: E402

# ---------------------------------------------------------------------------
# Вход: статы — редактировать прямо здесь между прогонами калибровки.
# ---------------------------------------------------------------------------

PLAYER_STATS = {"hp_max": 50, "strength": 10, "agility": 5, "luck": 2}

ENEMY_PRESETS = {
    "mouse": {"hp_max": 20, "strength": 5, "agility": 2, "luck": 1},
    "wolf": {"hp_max": 50, "strength": 12, "agility": 6, "luck": 2},
    "boar": {"hp_max": 70, "strength": 11, "agility": 6, "luck": 2},
}

# Черновые константы формул (§4-6, §8) — тоже предмет калибровки. Единые для
# обеих сторон: разница только в том, чей стат подставляется в формулу.
DODGE_K = 15
DOUBLE_STRIKE_K = 15
FLEE_MAX_FACES = 4
FLEE_K = 15
FLEE_THRESHOLD_PERCENT = cm.FLEE_THRESHOLD_PERCENT_DEFAULT
CIRCUMSTANCE_MODIFIER_PERCENT = cm.CIRCUMSTANCE_MODIFIER_PERCENT_DEFAULT

OUTCOMES = ("victory", "defeat", "player_fled", "enemy_fled")

# Стартовые статы персонажа для режима progression — из gameplay_loop_mvp.md §2
# (не PLAYER_STATS выше: та структура — фиксированный матчап для режима single).
CHARACTER_BASE_STATS = {"strength": 3, "agility": 3, "luck": 1, "vitality": 3}
CHARACTER_STARTING_POOL = 5

ROTATION_ORDER = ["strength", "agility", "luck", "vitality"]

CHECKPOINT_INTERVAL = 10
CHECKPOINT_FIGHTS = 400  # поднято со 100 — меньше шума в % на контрольных точках

ENCOUNTER_ORDER = ("mouse", "wolf", "boar")  # §6 gameplay_loop_mvp.md: 50/30/20 на d10


# ---------------------------------------------------------------------------
# Один бой
# ---------------------------------------------------------------------------


def _new_fighter(stats: dict) -> dict:
    return {
        "hp": stats["hp_max"],
        "hp_max": stats["hp_max"],
        "strength": stats["strength"],
        "agility": stats["agility"],
        "luck": stats["luck"],
        "flee_right_used": False,
    }


def _fight_result(
    result, turns, player, enemy, double_strikes, circumstance_outcome, circumstance_roller, flee_offers
) -> dict:
    return {
        "result": result,
        "rounds": (turns + 1) // 2,
        "player_hp_remaining": player["hp"],
        "enemy_hp_remaining": enemy["hp"],
        "player_double_strikes": double_strikes["player"],
        "enemy_double_strikes": double_strikes["enemy"],
        "circumstance_outcome": circumstance_outcome,
        "circumstance_roller": circumstance_roller,
        "flee_opportunities_offered": flee_offers,
    }


def _wants_to_flee(role: str, policy: str) -> bool:
    """§7: бот всегда бежит, если открылась возможность. Игрок решает по policy."""
    if role == "enemy":
        return True
    return policy == "flee_when_possible"


def simulate_single_fight(player_stats: dict, enemy_stats: dict, policy: str, rng, power_attack: bool = False) -> dict:
    player = _new_fighter(player_stats)
    enemy = _new_fighter(enemy_stats)

    # 1. Инициатива (§9 шаг 1). Ничья -> перебросить (формула не определяет тай-брейк).
    while True:
        player_roll = rng.randint(1, 10)
        enemy_roll = rng.randint(1, 10)
        initiative = cm.resolve_initiative(player_roll, enemy_roll)
        if initiative is not None:
            break
    first_role = "player" if initiative == "first" else "enemy"
    second_role = "enemy" if first_role == "player" else "player"

    # 2. Обстоятельство — кидает победитель инициативы (§8).
    circumstance_roller = first_role
    circumstance_outcome = cm.resolve_circumstance_outcome(rng.randint(1, 10))
    roller = player if circumstance_roller == "player" else enemy
    roller["strength"] = cm.apply_circumstance_strength_modifier(
        roller["strength"], circumstance_outcome, CIRCUMSTANCE_MODIFIER_PERCENT
    )

    double_strikes = {"player": 0, "enemy": 0}
    flee_offers = 0

    # 3. Выбор игрока "принять бой / отступить" — предлагается всегда (§9 шаг 3),
    # но для целей симулятора игрок здесь всегда выбирает "Принять бой": эта
    # развилка не зависит от --policy, в отличие от выбора по HP-порогу (§6)
    # внутри самого боя, где policy определяет решение на шаге 4 ниже.

    # ЦИКЛ ХОДОВ (§9 шаги 4-7)
    turn_order = (first_role, second_role)
    turns_taken = 0

    while True:
        attacker_role = turn_order[turns_taken % 2]
        defender_role = turn_order[(turns_taken + 1) % 2]
        attacker = player if attacker_role == "player" else enemy
        defender = player if defender_role == "player" else enemy

        # 4. Возможность побега по HP-порогу (§6) — своя, независимая, сторона атакующего.
        if not attacker["flee_right_used"] and cm.is_hp_at_or_below_flee_threshold(
            attacker["hp"], attacker["hp_max"], FLEE_THRESHOLD_PERCENT
        ):
            attacker["flee_right_used"] = True  # §6: одна попытка за бой, право сгорает сразу при броске
            luck_roll = rng.randint(1, 10)
            faces = cm.calculate_flee_opportunity_success_faces(attacker["luck"], FLEE_MAX_FACES, FLEE_K)
            if cm.is_flee_opportunity_triggered(luck_roll, faces):
                flee_offers += 1
                if _wants_to_flee(attacker_role, policy):
                    pursuer_attack_roll = rng.randint(1, 10)
                    flee = cm.resolve_flee_attempt(defender["strength"], pursuer_attack_roll, attacker["hp"])
                    attacker["hp"] = flee.fleeing_hp_after
                    if flee.fleeing_defeated:
                        result = "defeat" if attacker_role == "player" else "victory"
                    else:
                        result = "player_fled" if attacker_role == "player" else "enemy_fled"
                    return _fight_result(
                        result, turns_taken, player, enemy, double_strikes, circumstance_outcome, circumstance_roller, flee_offers
                    )

        # 5. Проверка двойного удара (§5).
        ds_faces = cm.calculate_double_strike_success_faces(attacker["luck"], DOUBLE_STRIKE_K)
        triggered = cm.is_double_strike_triggered(rng.randint(1, 10), ds_faces)
        num_strikes = 2 if triggered else 1
        if triggered:
            double_strikes[attacker_role] += 1

        # 6. Удар(ы).
        for _ in range(num_strikes):
            # §3a: мощный удар доступен только игроку — мобы им не пользуются.
            strike = cm.resolve_strike(
                attacker_strength=attacker["strength"],
                defender_agility=defender["agility"],
                attack_roll=rng.randint(1, 10),
                dodge_roll=rng.randint(1, 10),
                dodge_k=DODGE_K,
                power_attack=power_attack and attacker_role == "player",
            )
            defender["hp"] = max(defender["hp"] - strike.damage, 0)
            if defender["hp"] <= 0:
                turns_taken += 1
                result = "victory" if attacker_role == "player" else "defeat"
                return _fight_result(
                    result, turns_taken, player, enemy, double_strikes, circumstance_outcome, circumstance_roller, flee_offers
                )

        # 7. Ход переходит другой стороне.
        turns_taken += 1


# ---------------------------------------------------------------------------
# Батч боёв и агрегация
# ---------------------------------------------------------------------------


def run_batch(
    enemy_name: str, enemy_stats: dict, player_stats: dict, fights: int, policy: str, rng, power_attack: bool = False
) -> list:
    return [simulate_single_fight(player_stats, enemy_stats, policy, rng, power_attack) for _ in range(fights)]


def summarize(results: list, enemy_name: str) -> dict:
    n = len(results)
    outcome_counts = {outcome: 0 for outcome in OUTCOMES}
    for r in results:
        outcome_counts[r["result"]] += 1

    rounds = [r["rounds"] for r in results]
    victories = [r for r in results if r["result"] == "victory"]
    player_hp_on_victory = [r["player_hp_remaining"] for r in victories]

    circumstance_counts = {"debuff": 0, None: 0, "buff": 0}
    for r in results:
        circumstance_counts[r["circumstance_outcome"]] += 1

    rewards = [pr.calculate_battle_reward(r["result"], enemy_name) for r in results]

    return {
        "n": n,
        "outcome_percent": {o: 100 * outcome_counts[o] / n for o in OUTCOMES},
        "rounds_mean": statistics.mean(rounds),
        "rounds_median": statistics.median(rounds),
        "player_hp_on_victory_mean": statistics.mean(player_hp_on_victory) if victories else None,
        "player_double_strikes_avg": statistics.mean(r["player_double_strikes"] for r in results),
        "enemy_double_strikes_avg": statistics.mean(r["enemy_double_strikes"] for r in results),
        "circumstance_percent": {
            "debuff": 100 * circumstance_counts["debuff"] / n,
            "none": 100 * circumstance_counts[None] / n,
            "buff": 100 * circumstance_counts["buff"] / n,
        },
        "flee_opportunities_avg": statistics.mean(r["flee_opportunities_offered"] for r in results),
        "reward_avg": statistics.mean(rewards),
    }


# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------


def print_summary(enemy_name: str, fights: int, policy: str, seed, summary: dict, power_attack: bool = False) -> None:
    print(f"\n=== {enemy_name} | fights={fights} | policy={policy} | power_attack={power_attack} | seed={seed} ===")
    print("Исходы:")
    for outcome in OUTCOMES:
        print(f"  {outcome:<13} {summary['outcome_percent'][outcome]:5.1f}%")
    print(f"\nРаунды: среднее={summary['rounds_mean']:.1f}  медиана={summary['rounds_median']:.1f}")
    hp_victory = summary["player_hp_on_victory_mean"]
    hp_victory_str = f"{hp_victory:.1f}" if hp_victory is not None else "н/д (побед не было)"
    print(f"HP игрока при победе: среднее={hp_victory_str} (из {PLAYER_STATS['hp_max']})")
    print(
        f"Двойной удар: игрок avg/бой={summary['player_double_strikes_avg']:.2f}"
        f"   противник avg/бой={summary['enemy_double_strikes_avg']:.2f}"
    )
    cp = summary["circumstance_percent"]
    print(f"Обстоятельство: debuff={cp['debuff']:.1f}%  none={cp['none']:.1f}%  buff={cp['buff']:.1f}%  (ориентир: 20/60/20)")
    print(f"Возможности побега: среднее/бой={summary['flee_opportunities_avg']:.2f}")
    print(f"Награда: среднее victory points/бой={summary['reward_avg']:.2f}")


def print_comparison(summaries: dict) -> None:
    print("\n=== Сравнение по противникам ===")
    header = f"{'moba':<8} {'victory%':>9} {'defeat%':>9} {'rounds avg':>11} {'hp@victory':>11}"
    print(header)
    print("-" * len(header))
    for enemy_name, summary in summaries.items():
        hp_victory = summary["player_hp_on_victory_mean"]
        hp_str = f"{hp_victory:.1f}" if hp_victory is not None else "н/д"
        print(
            f"{enemy_name:<8} {summary['outcome_percent']['victory']:9.1f} "
            f"{summary['outcome_percent']['defeat']:9.1f} {summary['rounds_mean']:11.1f} {hp_str:>11}"
        )


def save_results(enemy_name: str, results: list, timestamp: str) -> Path:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / f"simulation_results_{enemy_name}_{timestamp}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Режим progression: персонаж растёт от боя к бою в рамках одной сессии
# ---------------------------------------------------------------------------


def roll_enemy_encounter(rng, level: int) -> str:
    """§6 gameplay_loop_mvp.md: d10, грани по pr.calculate_encounter_faces(level)."""
    mouse_faces, wolf_faces, _boar_faces = pr.calculate_encounter_faces(level)
    roll = rng.randint(1, 10)
    if roll <= mouse_faces:
        return "mouse"
    if roll <= mouse_faces + wolf_faces:
        return "wolf"
    return "boar"


PRIORITY_STR_VIT_TARGET_SUM = 8  # "~6-8 очков суммарно" (Сила+Здоровье) — верхняя граница диапазона
PRIORITY_SINGLE_STAT_TARGET = 7  # "~6-8 очков" для одного стата — середина диапазона

# Порядок вторичной ротации после приоритетной фазы — тоже блинд-ротация по
# total_points_spent % len(...), тем же принципом, что и ROTATION_ORDER.
SECONDARY_ORDER_EXCLUDING_AGILITY = ["strength", "luck", "vitality"]
SECONDARY_ORDER_EXCLUDING_LUCK = ["strength", "agility", "vitality"]
SKIP_AGILITY_LUCK_ORDER = ["strength", "vitality"]


def choose_stat_to_allocate(policy: str, current_stats: dict, total_points_spent: int) -> str:
    """Решает, какой стат прокачать в рамках симуляции игровой сессии. Это НЕ
    часть игровой логики — в реальной игре выбор делает игрок через кнопку;
    функция существует только для автопрогона симулятора. Не изменяет статы и
    не тратит очки сама — только называет стат, allocate_stat_point (core/) —
    отдельным вызовом на стороне вызывающего кода.

    policy == "round_robin": слепая ротация по ROTATION_ORDER, определяется
    через total_points_spent % len(ROTATION_ORDER) — НЕ зависит от текущих
    значений статов. Это принципиально: стартовые статы персонажа не равны
    между собой (Удача ниже остальных, см. gameplay_loop_mvp.md §2), и если бы
    ротация опиралась на "качать стат с наименьшим текущим значением", ранние
    очки систематически утекали бы в Удачу как в самый маленький стат — это
    уже не round-robin и исказило бы диагностику калибровки.

    policy == "priority_str_vit": сначала Сила и Здоровье поровну (тот из
    двух, что сейчас меньше), пока их сумма не достигнет
    PRIORITY_STR_VIT_TARGET_SUM — это преимущество только в первых очках, не
    заморозка навсегда: после порога распределение продолжается слепой
    ротацией по ROTATION_ORDER среди ВСЕХ ЧЕТЫРЁХ статов (включая Силу и
    Здоровье), просто без приоритета.

    policy == "priority_agility" / "priority_luck": сначала один стат
    (Ловкость / Удача соответственно) до PRIORITY_SINGLE_STAT_TARGET, затем
    слепая ротация (как в round_robin) по остальным трём статам.

    policy == "skip_agility_luck": слепая ротация ТОЛЬКО между Силой и
    Здоровьем, без переключения на Ловкость/Удачу вообще — нижняя граница
    эффекта для сравнения с priority_str_vit (та в итоге всё равно уходит в
    Ловкость/Удачу, эта — никогда).
    """
    if policy == "round_robin":
        return ROTATION_ORDER[total_points_spent % len(ROTATION_ORDER)]
    if policy == "priority_str_vit":
        if current_stats["strength"] + current_stats["vitality"] < PRIORITY_STR_VIT_TARGET_SUM:
            return "strength" if current_stats["strength"] <= current_stats["vitality"] else "vitality"
        return ROTATION_ORDER[total_points_spent % len(ROTATION_ORDER)]
    if policy == "priority_agility":
        if current_stats["agility"] < PRIORITY_SINGLE_STAT_TARGET:
            return "agility"
        order = SECONDARY_ORDER_EXCLUDING_AGILITY
        return order[total_points_spent % len(order)]
    if policy == "priority_luck":
        if current_stats["luck"] < PRIORITY_SINGLE_STAT_TARGET:
            return "luck"
        order = SECONDARY_ORDER_EXCLUDING_LUCK
        return order[total_points_spent % len(order)]
    if policy == "skip_agility_luck":
        return SKIP_AGILITY_LUCK_ORDER[total_points_spent % len(SKIP_AGILITY_LUCK_ORDER)]
    raise ValueError(f"unknown allocation policy: {policy!r}")


def _spend_all_points(policy: str, stats: dict, unspent_points: int, total_points_spent: int) -> tuple:
    """Тратит весь unspent_points по одному очку через choose_stat_to_allocate
    + core.progression.allocate_stat_point (её саму не дублирует)."""
    stats = dict(stats)
    while unspent_points > 0:
        stat = choose_stat_to_allocate(policy, stats, total_points_spent)
        unspent_points, stats[stat] = pr.allocate_stat_point(unspent_points, stats[stat], stat)
        total_points_spent += 1
    return stats, unspent_points, total_points_spent


def _run_checkpoint_probe(character_stats: dict, checkpoint_rng) -> dict:
    """Мини-прогон CHECKPOINT_FIGHTS боёв против каждого моба на текущих
    статах — не влияет на состояние самой сессии (свой RNG, отдельный от
    основного потока сессии, чтобы частота контрольных точек не меняла исход
    последующих боёв сессии при фиксированном --seed)."""
    winrates = {}
    for enemy_name in ENCOUNTER_ORDER:
        results = run_batch(
            enemy_name, ENEMY_PRESETS[enemy_name], character_stats, CHECKPOINT_FIGHTS, "always_fight", checkpoint_rng
        )
        wins = sum(1 for r in results if r["result"] == "victory")
        winrates[enemy_name] = 100 * wins / CHECKPOINT_FIGHTS
    return winrates


def simulate_progression_session(
    session_fights: int,
    policy: str,
    rng,
    checkpoint_rng,
    stat_points_per_level: int = pr.STAT_POINTS_PER_LEVEL,
) -> tuple:
    """Одна сессия: персонаж растёт от старта до session_fights-го боя.
    Возвращает (trajectory — запись по каждому бою, checkpoints — срезы силы
    персонажа каждые CHECKPOINT_INTERVAL боёв)."""
    stats = dict(CHARACTER_BASE_STATS)
    unspent_points = CHARACTER_STARTING_POOL
    total_points_spent = 0
    stats, unspent_points, total_points_spent = _spend_all_points(policy, stats, unspent_points, total_points_spent)
    stats["hp_max"] = pr.calculate_hp_max(stats["vitality"])

    victory_points = 0
    level = 1
    trajectory = []
    checkpoints = []

    for fight_index in range(1, session_fights + 1):
        enemy_name = roll_enemy_encounter(rng, level)
        fight_result = simulate_single_fight(stats, ENEMY_PRESETS[enemy_name], "always_fight", rng)

        reward = pr.calculate_battle_reward(fight_result["result"], enemy_name)
        old_points = victory_points
        victory_points += reward
        levels_gained = pr.calculate_levels_gained(old_points, victory_points)
        if levels_gained > 0:
            level += levels_gained
            unspent_points += pr.calculate_stat_points_gained(levels_gained, stat_points_per_level)
            stats, unspent_points, total_points_spent = _spend_all_points(
                policy, stats, unspent_points, total_points_spent
            )
            stats["hp_max"] = pr.calculate_hp_max(stats["vitality"])

        trajectory.append(
            {
                "fight_index": fight_index,
                "enemy": enemy_name,
                "result": fight_result["result"],
                "reward": reward,
                "victory_points": victory_points,
                "level": level,
                "stats": dict(stats),
            }
        )

        if fight_index % CHECKPOINT_INTERVAL == 0:
            winrates = _run_checkpoint_probe(stats, checkpoint_rng)
            checkpoints.append(
                {
                    "fight_index": fight_index,
                    "level": level,
                    "winrate_mouse": winrates["mouse"],
                    "winrate_wolf": winrates["wolf"],
                    "winrate_boar": winrates["boar"],
                    "strength": stats["strength"],
                    "agility": stats["agility"],
                    "luck": stats["luck"],
                    "vitality": stats["vitality"],
                }
            )

    return trajectory, checkpoints


def print_progression_table(checkpoints: list) -> None:
    header = (
        f"{'бой':>5} {'уровень':>7} {'мышь%':>7} {'волк%':>7} {'кабан%':>7} "
        f"{'str':>4} {'agi':>4} {'luck':>4} {'vit':>4}"
    )
    print(f"\n=== Прогрессия по контрольным точкам (каждые {CHECKPOINT_INTERVAL} боёв) ===")
    print(header)
    print("-" * len(header))
    for row in checkpoints:
        print(
            f"{row['fight_index']:>5} {row['level']:>7} "
            f"{row['winrate_mouse']:>7.1f} {row['winrate_wolf']:>7.1f} {row['winrate_boar']:>7.1f} "
            f"{row['strength']:>4} {row['agility']:>4} {row['luck']:>4} {row['vitality']:>4}"
        )
    if checkpoints:
        last = checkpoints[-1]
        print(f"\n% побед против кабана на {last['fight_index']}-м бою: {last['winrate_boar']:.1f}%")


def save_progression_results(trajectory: list, checkpoints: list, timestamp: str) -> Path:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / f"simulation_progression_{timestamp}.json"
    payload = {"trajectory": trajectory, "checkpoints": checkpoints}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def print_seed_comparison(per_seed_final: list, session_fights: int) -> None:
    """per_seed_final: список {"seed", "checkpoint" (последняя точка или None)}."""
    header = f"{'seed':>6} {'уровень':>7} {'волк%':>7} {'кабан%':>7}"
    print(f"\n=== Сравнение по {len(per_seed_final)} seed'ам (бой {session_fights}) ===")
    print(header)
    print("-" * len(header))

    wolf_values, boar_values = [], []
    for entry in per_seed_final:
        cp = entry["checkpoint"]
        if cp is None:
            print(f"{entry['seed']:>6}   (нет контрольных точек — session-fights < {CHECKPOINT_INTERVAL})")
            continue
        print(f"{entry['seed']:>6} {cp['level']:>7} {cp['winrate_wolf']:>7.1f} {cp['winrate_boar']:>7.1f}")
        wolf_values.append(cp["winrate_wolf"])
        boar_values.append(cp["winrate_boar"])

    if not wolf_values:
        return

    print(f"\n{'показатель':<20} {'мин':>7} {'макс':>7} {'среднее':>9} {'медиана':>9}")
    for label, values in (("волк% на посл. бою", wolf_values), ("кабан% на посл. бою", boar_values)):
        print(
            f"{label:<20} {min(values):>7.1f} {max(values):>7.1f} "
            f"{statistics.mean(values):>9.1f} {statistics.median(values):>9.1f}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["single", "progression"], default="single")
    parser.add_argument("--enemy", choices=[*ENEMY_PRESETS.keys(), "all"], default="all")
    parser.add_argument("--fights", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--policy", choices=["always_fight", "flee_when_possible"], default="always_fight")
    parser.add_argument(
        "--power-attack",
        action="store_true",
        help="Игрок всегда использует '💥 Мощный удар' (§3a docs/combat_mechanics.md) вместо обычной атаки — для калибровки эффекта.",
    )
    parser.add_argument("--session-fights", type=int, default=100)
    parser.add_argument(
        "--allocation-policy",
        choices=["round_robin", "priority_str_vit", "priority_agility", "priority_luck", "skip_agility_luck"],
        default="round_robin",
    )
    parser.add_argument("--stat-points-per-level", type=int, default=pr.STAT_POINTS_PER_LEVEL)
    parser.add_argument(
        "--seeds",
        type=str,
        default=None,
        help='progression-режим: сравнить несколько seed через запятую, напр. "1,7,42,100,2024" (вместо --seed)',
    )
    args = parser.parse_args()

    if args.seeds is not None and args.mode == "single":
        parser.error("--seeds поддерживается только с --mode progression, не с --mode single")

    return args


def run_single_mode(args, rng, timestamp) -> None:
    enemy_names = list(ENEMY_PRESETS.keys()) if args.enemy == "all" else [args.enemy]

    summaries = {}
    for enemy_name in enemy_names:
        enemy_stats = ENEMY_PRESETS[enemy_name]
        results = run_batch(enemy_name, enemy_stats, PLAYER_STATS, args.fights, args.policy, rng, args.power_attack)
        summary = summarize(results, enemy_name)
        summaries[enemy_name] = summary
        print_summary(enemy_name, args.fights, args.policy, args.seed, summary, args.power_attack)
        out_path = save_results(enemy_name, results, timestamp)
        print(f"Сырые результаты сохранены: {out_path}")

    if len(enemy_names) > 1:
        print_comparison(summaries)


def run_progression_mode(args, rng, timestamp) -> None:
    if args.seeds is not None:
        run_progression_multi_seed(args, timestamp)
        return

    # Отдельный, независимый от основного, RNG для мини-прогонов на контрольных
    # точках — см. docstring _run_checkpoint_probe.
    checkpoint_seed = None if args.seed is None else args.seed + 1_000_000
    checkpoint_rng = random.Random(checkpoint_seed)

    print(
        f"\n=== progression | session-fights={args.session_fights} "
        f"| allocation-policy={args.allocation_policy} | stat-points-per-level={args.stat_points_per_level} "
        f"| seed={args.seed} ==="
    )
    trajectory, checkpoints = simulate_progression_session(
        args.session_fights, args.allocation_policy, rng, checkpoint_rng, args.stat_points_per_level
    )
    print_progression_table(checkpoints)
    out_path = save_progression_results(trajectory, checkpoints, timestamp)
    print(f"\nПолная траектория сохранена: {out_path}")


def run_progression_multi_seed(args, timestamp) -> None:
    seeds = [int(s.strip()) for s in args.seeds.split(",")]
    print(
        f"\n=== progression multi-seed | seeds={seeds} | session-fights={args.session_fights} "
        f"| allocation-policy={args.allocation_policy} | stat-points-per-level={args.stat_points_per_level} ==="
    )

    per_seed_final = []
    for seed in seeds:
        rng = random.Random(seed)
        checkpoint_rng = random.Random(seed + 1_000_000)
        trajectory, checkpoints = simulate_progression_session(
            args.session_fights, args.allocation_policy, rng, checkpoint_rng, args.stat_points_per_level
        )
        out_path = save_progression_results(trajectory, checkpoints, f"{timestamp}_seed{seed}")
        print(f"seed={seed}: траектория сохранена в {out_path}")
        per_seed_final.append({"seed": seed, "checkpoint": checkpoints[-1] if checkpoints else None})

    print_seed_comparison(per_seed_final, args.session_fights)


def main():
    args = parse_args()
    rng = random.Random(args.seed)
    timestamp = time.strftime("%Y%m%dT%H%M%S")

    if args.mode == "single":
        run_single_mode(args, rng, timestamp)
    else:
        run_progression_mode(args, rng, timestamp)


if __name__ == "__main__":
    main()
