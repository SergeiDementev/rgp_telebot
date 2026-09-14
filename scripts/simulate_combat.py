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
    "wolf": {"hp_max": 60, "strength": 15, "agility": 8, "luck": 3},
    "boar": {"hp_max": 120, "strength": 25, "agility": 5, "luck": 2},
}

# Черновые константы формул (§4-6, §8) — тоже предмет калибровки. Единые для
# обеих сторон: разница только в том, чей стат подставляется в формулу.
DODGE_MAX_FACES = 5
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

STAT_ALLOCATION_ORDER = ("strength", "agility", "luck", "vitality")

CHECKPOINT_INTERVAL = 10
CHECKPOINT_FIGHTS = 100

ENCOUNTER_ORDER = ("mouse", "wolf", "boar")  # §6 gameplay_loop_mvp.md: 60/30/10 на d10


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


def simulate_single_fight(player_stats: dict, enemy_stats: dict, policy: str, rng) -> dict:
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
                attacker["flee_right_used"] = True  # отказ -> право сгорает навсегда

        # 5. Проверка двойного удара (§5).
        ds_faces = cm.calculate_double_strike_success_faces(attacker["luck"], DOUBLE_STRIKE_K)
        triggered = cm.is_double_strike_triggered(rng.randint(1, 10), ds_faces)
        num_strikes = 2 if triggered else 1
        if triggered:
            double_strikes[attacker_role] += 1

        # 6. Удар(ы).
        for _ in range(num_strikes):
            strike = cm.resolve_strike(
                attacker_strength=attacker["strength"],
                defender_agility=defender["agility"],
                attack_roll=rng.randint(1, 10),
                dodge_roll=rng.randint(1, 10),
                dodge_max_faces=DODGE_MAX_FACES,
                dodge_k=DODGE_K,
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


def run_batch(enemy_name: str, enemy_stats: dict, player_stats: dict, fights: int, policy: str, rng) -> list:
    return [simulate_single_fight(player_stats, enemy_stats, policy, rng) for _ in range(fights)]


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


def print_summary(enemy_name: str, fights: int, policy: str, seed, summary: dict) -> None:
    print(f"\n=== {enemy_name} | fights={fights} | policy={policy} | seed={seed} ===")
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


def roll_enemy_encounter(rng) -> str:
    """§6 gameplay_loop_mvp.md: d10, 1-6 мышь / 7-9 волк / 10 кабан. Фиксировано весь MVP."""
    roll = rng.randint(1, 10)
    if roll <= 6:
        return "mouse"
    if roll <= 9:
        return "wolf"
    return "boar"


def round_robin_allocation_policy(
    character_stats: dict, unspent_points: int, points_spent_so_far: int
) -> tuple:
    """Заглушка политики распределения очков: Сила -> Ловкость -> Удача ->
    Здоровье -> по кругу. Контракт входа/выхода для любой allocation_policy:
    (статы, доступные очки, счётчик уже потраченных очков за сессию) ->
    (новые статы, новые доступные очки [обычно 0], новый счётчик). Тратит все
    unspent_points за один вызов, используя core.progression.allocate_stat_point
    (не дублирует его логику). Чтобы добавить другую стратегию — реализовать
    функцию с той же сигнатурой и зарегистрировать в ALLOCATION_POLICIES.
    """
    stats = dict(character_stats)
    spent = points_spent_so_far
    while unspent_points > 0:
        stat = STAT_ALLOCATION_ORDER[spent % len(STAT_ALLOCATION_ORDER)]
        unspent_points, stats[stat] = pr.allocate_stat_point(unspent_points, stats[stat], stat)
        spent += 1
    return stats, unspent_points, spent


ALLOCATION_POLICIES = {"round_robin": round_robin_allocation_policy}


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


def simulate_progression_session(session_fights: int, allocation_policy, rng, checkpoint_rng) -> tuple:
    """Одна сессия: персонаж растёт от старта до session_fights-го боя.
    Возвращает (trajectory — запись по каждому бою, checkpoints — срезы силы
    персонажа каждые CHECKPOINT_INTERVAL боёв)."""
    stats = dict(CHARACTER_BASE_STATS)
    unspent_points = CHARACTER_STARTING_POOL
    points_spent = 0
    stats, unspent_points, points_spent = allocation_policy(stats, unspent_points, points_spent)
    stats["hp_max"] = pr.calculate_hp_max(stats["vitality"])

    victory_points = 0
    level = 1
    trajectory = []
    checkpoints = []

    for fight_index in range(1, session_fights + 1):
        enemy_name = roll_enemy_encounter(rng)
        fight_result = simulate_single_fight(stats, ENEMY_PRESETS[enemy_name], "always_fight", rng)

        reward = pr.calculate_battle_reward(fight_result["result"], enemy_name)
        old_points = victory_points
        victory_points += reward
        levels_gained = pr.calculate_levels_gained(old_points, victory_points)
        if levels_gained > 0:
            level += levels_gained
            unspent_points += levels_gained
            stats, unspent_points, points_spent = allocation_policy(stats, unspent_points, points_spent)
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
                }
            )

    return trajectory, checkpoints


def print_progression_table(checkpoints: list) -> None:
    header = f"{'бой':>5} {'уровень':>7} {'мышь%':>7} {'волк%':>7} {'кабан%':>7}"
    print(f"\n=== Прогрессия по контрольным точкам (каждые {CHECKPOINT_INTERVAL} боёв) ===")
    print(header)
    print("-" * len(header))
    for row in checkpoints:
        print(
            f"{row['fight_index']:>5} {row['level']:>7} "
            f"{row['winrate_mouse']:>7.1f} {row['winrate_wolf']:>7.1f} {row['winrate_boar']:>7.1f}"
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
    parser.add_argument("--session-fights", type=int, default=100)
    parser.add_argument("--allocation-policy", choices=list(ALLOCATION_POLICIES.keys()), default="round_robin")
    return parser.parse_args()


def run_single_mode(args, rng, timestamp) -> None:
    enemy_names = list(ENEMY_PRESETS.keys()) if args.enemy == "all" else [args.enemy]

    summaries = {}
    for enemy_name in enemy_names:
        enemy_stats = ENEMY_PRESETS[enemy_name]
        results = run_batch(enemy_name, enemy_stats, PLAYER_STATS, args.fights, args.policy, rng)
        summary = summarize(results, enemy_name)
        summaries[enemy_name] = summary
        print_summary(enemy_name, args.fights, args.policy, args.seed, summary)
        out_path = save_results(enemy_name, results, timestamp)
        print(f"Сырые результаты сохранены: {out_path}")

    if len(enemy_names) > 1:
        print_comparison(summaries)


def run_progression_mode(args, rng, timestamp) -> None:
    allocation_policy = ALLOCATION_POLICIES[args.allocation_policy]
    # Отдельный, независимый от основного, RNG для мини-прогонов на контрольных
    # точках — см. docstring _run_checkpoint_probe.
    checkpoint_seed = None if args.seed is None else args.seed + 1_000_000
    checkpoint_rng = random.Random(checkpoint_seed)

    print(
        f"\n=== progression | session-fights={args.session_fights} "
        f"| allocation-policy={args.allocation_policy} | seed={args.seed} ==="
    )
    trajectory, checkpoints = simulate_progression_session(args.session_fights, allocation_policy, rng, checkpoint_rng)
    print_progression_table(checkpoints)
    out_path = save_progression_results(trajectory, checkpoints, timestamp)
    print(f"\nПолная траектория сохранена: {out_path}")


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
