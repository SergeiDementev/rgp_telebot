"""Калибровка статов финального босса (docs/notes.md) — отдельный файл, не
смешан с scripts/simulate_combat_economy.py (лут/золото боссу не нужны для
этой задачи, только зелья в одном специальном сценарии).

ЖЁСТКОЕ ОГРАНИЧЕНИЕ (как и в simulate_combat_economy.py): core/combat_
mechanics.py и core/progression.py не меняются — импортируются как есть.
scripts/simulate_combat.py и simulate_combat_economy.py тоже не трогаются,
только импортируются (`sc`/`sce`) — единственное скопированное место, как и
в simulate_combat_economy.py, это control-flow цикла ходов, на этот раз
чтобы поддержать отсутствие лимита "зелье раз за бой" в бою с боссом.

Два сценария теста (single-mode стиль — много боёв на фиксированных статах,
как scripts/simulate_combat.py --mode single):
  а) "Без подготовки" — 0 зелий. Целевой winrate 0-5%.
  б) "С полным запасом" — 5 малых + 3 больших зелья. Целевой winrate 40-70%.
Оба сценария (как и любой бой с боссом) без лимита "1 зелье за бой" —
это не черновое допущение калибровки, а реальное правило игры (docs/
notes.md, п.39: у финального босса этого лимита нет вообще, ограничивает
только инвентарь). Промежуточные точки между этими двумя крайними
запасами (частичный инвентарь) — scripts/simulate_boss_partial_stock.py,
переиспользует функции отсюда как есть.

Статы игрока для теста — не выдуманы, а взяты из реальной прогрессии:
compute_typical_level_9_10_stats() гоняет sc.simulate_progression_session
(проверенный движок как есть) по тем же 5 seed, что и в остальных
калибровках, и усредняет статы персонажа в чекпоинтах, где уровень 9 или 10.

Запуск:
    python scripts/simulate_boss.py
    python scripts/simulate_boss.py --fights 5000 --boss-hp 200 --boss-str 30 --boss-agi 11 --boss-luck 5
"""

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from core import combat_mechanics as cm  # noqa: E402
from core import economy as ec  # noqa: E402
from core import progression as pr  # noqa: E402
from scripts import simulate_combat as sc  # noqa: E402
from scripts import simulate_combat_economy as sce  # noqa: E402

PROBE_SEEDS = (1, 7, 42, 100, 2024)  # те же seed, что и во всех остальных калибровках сессии
PROBE_TARGET_LEVELS = (9, 10)
PROBE_SESSION_FIGHTS = 150  # с запасом — level 9-10 у всех 5 seed достигается к ~80-130 бою

# Откалибровано итеративно (docs/notes.md) от чернового кандидата
# hp_max=200/strength=30/agility=11/luck=5 (тот давал victory% ~1.4% даже с
# полным запасом зелий — слишком силён) вниз, пока оба целевых диапазона не
# сошлись одновременно и стабильно по всем 5 seed: без подготовки ~0.0%
# (цель 0-5%), с полным запасом ~43.5-45.1% (цель 40-70%).
BOSS_PRESET = {"hp_max": 150, "strength": 22, "agility": 9, "luck": 4}

FULL_STASH_SMALL_POTIONS = ec.SMALL_POTION_CAP  # "полный запас" буквально = кап на инвентарь
FULL_STASH_LARGE_POTIONS = ec.LARGE_POTION_CAP

# Право стороны enemy на попытку побега по HP-порогу (§6) — геймдизайн-флаг
# оркестрации симулятора, НЕ часть core/combat_mechanics.py (там формула
# самой попытки, а не то, кому вообще разрешено её пробовать). Финальный
# босс бьётся до конца — не убегает никогда. Типы, не перечисленные здесь,
# считаются True (см. .get(enemy_type, True) в месте использования) — право
# побега игрока эта настройка не ограничивает вообще, она только про enemy.
ENEMY_CAN_FLEE = {"boss": False}


# ---------------------------------------------------------------------------
# Статы игрока для теста — из реальной прогрессии, не выдуманы вручную.
# ---------------------------------------------------------------------------


def compute_typical_level_9_10_stats(seeds=PROBE_SEEDS, policy: str = "priority_str_vit") -> dict:
    """Гоняет sc.simulate_progression_session (движок как есть, без
    экономики — она не нужна для того, какие статы у типичного персонажа
    9-10 уровня) по каждому seed, собирает статы чекпоинтов на уровне 9-10
    (чекпоинты идут раз в sc.CHECKPOINT_INTERVAL боёв — не всегда точно
    попадают на 9/10, у части seed уровень может перескочить через них за
    один интервал; используем то, что попало). Возвращает среднее,
    округлённое до целого (статы — целые числа)."""
    samples = []
    for seed in seeds:
        rng = random.Random(seed)
        checkpoint_rng = random.Random(seed + 1_000_000)
        _trajectory, checkpoints = sc.simulate_progression_session(
            PROBE_SESSION_FIGHTS, policy, rng, checkpoint_rng, pr.STAT_POINTS_PER_LEVEL
        )
        samples.extend(c for c in checkpoints if c["level"] in PROBE_TARGET_LEVELS)

    if not samples:
        raise RuntimeError(
            f"ни один seed из {seeds} не дал чекпоинт на уровне {PROBE_TARGET_LEVELS} за {PROBE_SESSION_FIGHTS} боёв"
        )

    stats = {
        "strength": round(statistics.mean(s["strength"] for s in samples)),
        "agility": round(statistics.mean(s["agility"] for s in samples)),
        "luck": round(statistics.mean(s["luck"] for s in samples)),
        "vitality": round(statistics.mean(s["vitality"] for s in samples)),
    }
    stats["hp_max"] = pr.calculate_hp_max(stats["vitality"])
    return stats, len(samples)


# ---------------------------------------------------------------------------
# Один бой против босса — копия sce.simulate_single_fight_economy с одним
# отличием: снятый лимит "зелье раз за бой" — реальное правило боя с
# боссом (docs/notes.md, п.39), не черновое допущение калибровки.
# ---------------------------------------------------------------------------


def _maybe_drink_potion_unlimited(attacker: dict) -> None:
    """Как sce._maybe_drink_potion, но БЕЗ лимита "раз за бой" — у финального
    босса этого лимита нет вообще (docs/notes.md, п.39), ограничивает
    только реальный инвентарь. Переиспользует core.economy.choose_potion_
    to_drink/calculate_heal_amount как есть, не дублирует условия
    триггера/приоритета/процента лечения."""
    if not ec.is_hp_at_or_below_heal_threshold(attacker["hp"], attacker["hp_max"]):
        return
    potion = ec.choose_potion_to_drink(attacker["potions_small"], attacker["potions_large"])
    if potion is None:
        return
    if potion == "large":
        attacker["potions_large"] -= 1
        attacker["potions_large_used"] += 1
    else:
        attacker["potions_small"] -= 1
        attacker["potions_small_used"] += 1
    attacker["hp"] = min(attacker["hp"] + ec.calculate_heal_amount(attacker["hp_max"], potion), attacker["hp_max"])
    attacker["potions_used_count"] += 1


def simulate_single_fight_vs_boss(
    player_stats: dict,
    boss_stats: dict,
    policy: str,
    rng,
    potions_small: int,
    potions_large: int,
    unlimited_potions: bool,
    enemy_type: str = "boss",
    power_attack: bool = False,
) -> dict:
    """Копия sce.simulate_single_fight_economy (см. её docstring и docstring
    модуля — почему копия, а не правка оригинала/sce). Формулы по-прежнему
    идут через cm.*/sc._fight_result/sc._new_fighter/sc._wants_to_flee —
    копируется только control-flow, чтобы вставить исцеление (и для
    сценария б снять с него лимит "раз за бой"), и чтобы для стороны enemy
    учитывать ENEMY_CAN_FLEE — финальный босс никогда не пытается сбежать."""
    player = sc._new_fighter(player_stats)
    enemy = sc._new_fighter(boss_stats)
    player["potions_small"] = potions_small
    player["potions_large"] = potions_large
    player["potion_used_this_battle"] = False
    player["potions_used_count"] = 0
    player["potions_small_used"] = 0
    player["potions_large_used"] = 0

    while True:
        player_roll = rng.randint(1, 10)
        enemy_roll = rng.randint(1, 10)
        initiative = cm.resolve_initiative(player_roll, enemy_roll)
        if initiative is not None:
            break
    first_role = "player" if initiative == "first" else "enemy"
    second_role = "enemy" if first_role == "player" else "player"

    circumstance_roller = first_role
    circumstance_outcome = cm.resolve_circumstance_outcome(rng.randint(1, 10))
    roller = player if circumstance_roller == "player" else enemy
    roller["strength"] = cm.apply_circumstance_strength_modifier(
        roller["strength"], circumstance_outcome, sc.CIRCUMSTANCE_MODIFIER_PERCENT
    )

    double_strikes = {"player": 0, "enemy": 0}
    flee_offers = 0
    turn_order = (first_role, second_role)
    turns_taken = 0

    while True:
        attacker_role = turn_order[turns_taken % 2]
        defender_role = turn_order[(turns_taken + 1) % 2]
        attacker = player if attacker_role == "player" else enemy
        defender = player if defender_role == "player" else enemy

        if attacker_role == "player":
            if unlimited_potions:
                _maybe_drink_potion_unlimited(attacker)
            else:
                sce._maybe_drink_potion(attacker)

        # Побег недоступен этой стороне вовсе (docs/notes.md) — финальный
        # босс бьётся до конца. Пропускаем шаг целиком: ни флаг flee_right_
        # used не трогаем, ни is_hp_at_or_below_flee_threshold/calculate_
        # flee_opportunity_success_faces/is_flee_opportunity_triggered не
        # вызываем — обычный ход дальше. Игрока это никак не ограничивает.
        attacker_can_flee = attacker_role != "enemy" or ENEMY_CAN_FLEE.get(enemy_type, True)

        if attacker_can_flee and not attacker["flee_right_used"] and cm.is_hp_at_or_below_flee_threshold(
            attacker["hp"], attacker["hp_max"], sc.FLEE_THRESHOLD_PERCENT
        ):
            attacker["flee_right_used"] = True
            luck_roll = rng.randint(1, 10)
            faces = cm.calculate_flee_opportunity_success_faces(attacker["luck"], sc.FLEE_MAX_FACES, sc.FLEE_K)
            if cm.is_flee_opportunity_triggered(luck_roll, faces):
                flee_offers += 1
                if sc._wants_to_flee(attacker_role, policy):
                    pursuer_attack_roll = rng.randint(1, 10)
                    flee = cm.resolve_flee_attempt(defender["strength"], pursuer_attack_roll, attacker["hp"])
                    attacker["hp"] = flee.fleeing_hp_after
                    if flee.fleeing_defeated:
                        result = "defeat" if attacker_role == "player" else "victory"
                    else:
                        result = "player_fled" if attacker_role == "player" else "enemy_fled"
                    fight_result = sc._fight_result(
                        result, turns_taken, player, enemy, double_strikes,
                        circumstance_outcome, circumstance_roller, flee_offers,
                    )
                    fight_result["potions_used_count"] = player["potions_used_count"]
                    fight_result["potions_small_used"] = player["potions_small_used"]
                    fight_result["potions_large_used"] = player["potions_large_used"]
                    return fight_result

        ds_faces = cm.calculate_double_strike_success_faces(attacker["luck"], sc.DOUBLE_STRIKE_K)
        triggered = cm.is_double_strike_triggered(rng.randint(1, 10), ds_faces)
        num_strikes = 2 if triggered else 1
        if triggered:
            double_strikes[attacker_role] += 1

        for _ in range(num_strikes):
            # §3a: мощный удар доступен только игроку — босс им не пользуется.
            strike = cm.resolve_strike(
                attacker_strength=attacker["strength"],
                defender_agility=defender["agility"],
                attack_roll=rng.randint(1, 10),
                dodge_roll=rng.randint(1, 10),
                dodge_k=sc.DODGE_K,
                power_attack=power_attack and attacker_role == "player",
            )
            defender["hp"] = max(defender["hp"] - strike.damage, 0)
            if defender["hp"] <= 0:
                turns_taken += 1
                result = "victory" if attacker_role == "player" else "defeat"
                fight_result = sc._fight_result(
                    result, turns_taken, player, enemy, double_strikes,
                    circumstance_outcome, circumstance_roller, flee_offers,
                )
                fight_result["potions_used_count"] = player["potions_used_count"]
                fight_result["potions_small_used"] = player["potions_small_used"]
                fight_result["potions_large_used"] = player["potions_large_used"]
                return fight_result

        turns_taken += 1


# ---------------------------------------------------------------------------
# Батч боёв + сводка (single-mode стиль sc.print_summary/print_comparison,
# без reward'а — pr.calculate_battle_reward не знает про "boss").
# ---------------------------------------------------------------------------


def run_boss_batch(
    player_stats, boss_stats, fights, rng, potions_small, potions_large, unlimited_potions, power_attack: bool = False
) -> list:
    return [
        simulate_single_fight_vs_boss(
            player_stats, boss_stats, "always_fight", rng, potions_small, potions_large, unlimited_potions,
            power_attack=power_attack,
        )
        for _ in range(fights)
    ]


def summarize_boss(results: list) -> dict:
    n = len(results)
    outcome_counts = {outcome: 0 for outcome in sc.OUTCOMES}
    for r in results:
        outcome_counts[r["result"]] += 1
    return {
        "n": n,
        "outcome_percent": {o: 100 * outcome_counts[o] / n for o in sc.OUTCOMES},
        "rounds_mean": statistics.mean(r["rounds"] for r in results),
        "potions_used_avg": statistics.mean(r["potions_used_count"] for r in results),
    }


def print_boss_summary(scenario_label: str, fights: int, summary: dict) -> None:
    print(f"\n=== Босс | {scenario_label} | fights={fights} ===")
    for outcome in sc.OUTCOMES:
        print(f"  {outcome:<13} {summary['outcome_percent'][outcome]:5.1f}%")
    print(f"Раунды: среднее={summary['rounds_mean']:.1f}")
    print(f"Зелий использовано в среднем/бой: {summary['potions_used_avg']:.2f}")


def print_two_scenario_table(no_prep_summary: dict, full_stash_summary: dict) -> None:
    print("\n=== Сводная таблица: без подготовки vs с полным запасом ===")
    header = f"{'сценарий':<20} {'victory%':>9} {'defeat%':>9} {'fled%':>9} {'rounds avg':>11} {'зелий/бой':>10}"
    print(header)
    print("-" * len(header))
    for label, summary in (("без подготовки (0)", no_prep_summary), ("с полным запасом", full_stash_summary)):
        fled_pct = summary["outcome_percent"]["player_fled"] + summary["outcome_percent"]["enemy_fled"]
        print(
            f"{label:<20} {summary['outcome_percent']['victory']:9.1f} {summary['outcome_percent']['defeat']:9.1f} "
            f"{fled_pct:9.1f} {summary['rounds_mean']:11.1f} {summary['potions_used_avg']:10.2f}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fights", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--boss-hp", type=int, default=BOSS_PRESET["hp_max"])
    parser.add_argument("--boss-str", type=int, default=BOSS_PRESET["strength"])
    parser.add_argument("--boss-agi", type=int, default=BOSS_PRESET["agility"])
    parser.add_argument("--boss-luck", type=int, default=BOSS_PRESET["luck"])
    return parser.parse_args()


def main():
    args = parse_args()
    boss_stats = {"hp_max": args.boss_hp, "strength": args.boss_str, "agility": args.boss_agi, "luck": args.boss_luck}

    player_stats, sample_count = compute_typical_level_9_10_stats()
    print(
        f"Статы игрока (типичный уровень {PROBE_TARGET_LEVELS} по {len(PROBE_SEEDS)} seed, "
        f"{sample_count} точек-чекпоинтов): {player_stats}"
    )
    print(f"Статы босса (кандидат): {boss_stats}")

    rng_a = random.Random(args.seed)
    results_a = run_boss_batch(player_stats, boss_stats, args.fights, rng_a, potions_small=0, potions_large=0, unlimited_potions=False)
    summary_a = summarize_boss(results_a)
    print_boss_summary("без подготовки (0 зелий)", args.fights, summary_a)

    rng_b = random.Random(args.seed + 1)
    results_b = run_boss_batch(
        player_stats, boss_stats, args.fights, rng_b,
        potions_small=FULL_STASH_SMALL_POTIONS, potions_large=FULL_STASH_LARGE_POTIONS, unlimited_potions=True,
    )
    summary_b = summarize_boss(results_b)
    print_boss_summary("с полным запасом (5 малых + 3 больших, без лимита)", args.fights, summary_b)

    print_two_scenario_table(summary_a, summary_b)


if __name__ == "__main__":
    main()
