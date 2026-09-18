"""Проверка, имеет ли смысл открывать финального босса раньше — с 8-го
уровня вместо текущего pr.BOSS_LEVEL_REQUIREMENT=9 (docs/notes.md).

Прогон 1 — естественный запас зелий на входе в 8-й уровень. Обычная
непрерывная progression-сессия С экономикой (лут/золото/покупка — тот же
цикл, что sce.simulate_progression_session_economy), с 1-го уровня, БЕЗ
сброса — как в реальной игре, никто не сбрасывает персонажа перед тем,
как впервые дойти до 8 уровня. Для каждого seed фиксируется
potions_small/potions_large сразу после того, как персонаж впервые
достиг 8 уровня (сразу после покупки в том же бою, где случился
левел-ап) — то, что реально оказалось в инвентаре к этому моменту
органической игры, а не то, сколько "следовало" бы накопить.

Прогон 2 — win rate на статах 8-го уровня против уже откалиброванного
scripts/simulate_boss.py::BOSS_PRESET, три точки запаса зелий:
  а) естественный (среднее по Прогону 1)
  б) 0 (контроль — совсем без подготовки)
  в) полный 5+3 (контроль — потолок инвентаря)
Без лимита "зелье раз за бой" — реальное правило боя с боссом (docs/
notes.md, п.39), не специфика калибровки.

Статы 8-го уровня усреднены той же инфраструктурой, что и 9-10 уровень
(scripts/simulate_boss.py::compute_typical_level_9_10_stats — sc.
simulate_progression_session, 5 seed), но по ПОЛНОЙ трассе боя за боем
(trajectory), а не по срезам раз в CHECKPOINT_INTERVAL=10 боёв: для
одного конкретного уровня чекпоинты оказались слишком редкими — всего 3
точки на все 5 seed, 2 seed вообще без единой (прогрессия перепрыгивает
через уровень 8 между соседними чекпоинтами). Трасса по каждому бою — та
же самая сессия и тот же rng, просто читается на каждом бою, а не раз в
10 — даёт 29 точек с представительством всех 5 seed.

Не расширяет ни scripts/simulate_boss.py, ни scripts/simulate_combat_
economy.py, ни scripts/simulate_combat.py — переиспользует все три как
есть (`sb`/`sce`/`sc`/`pr`).

Запуск:
    python -m scripts.simulate_boss_early_unlock
    python -m scripts.simulate_boss_early_unlock --fights-per-seed 2000
"""

import argparse
import csv
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from core import economy as ec  # noqa: E402
from core import progression as pr  # noqa: E402
from scripts import simulate_boss as sb  # noqa: E402
from scripts import simulate_combat as sc  # noqa: E402
from scripts import simulate_combat_economy as sce  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

TARGET_LEVEL = 8
PROBE_SEEDS = sb.PROBE_SEEDS  # (1, 7, 42, 100, 2024) — те же 5 seed, что и во всех калибровках сессии
STAT_ALLOCATION_POLICY = "priority_str_vit"
NATURAL_STOCK_MAX_FIGHTS = 400  # с запасом — уровень 8 в пробном прогоне достигался к ~60-120 бою
STATS_PROBE_SESSION_FIGHTS = sb.PROBE_SESSION_FIGHTS  # 150 — тот же, что и для 9-10 уровня
DEFAULT_FIGHTS_PER_SEED = 2000  # для Прогона 2 (боевая статистика), как в остальных прогонах сессии


# ---------------------------------------------------------------------------
# Прогон 1 — естественный запас зелий на входе в 8-й уровень
# ---------------------------------------------------------------------------


def run_natural_stock_at_level(target_level: int, seed: int, stat_policy: str, stat_points_per_level: int, max_fights: int) -> dict:
    """Непрерывная progression-сессия с экономикой, с 1-го уровня, без
    сброса — тот же цикл, что sce.simulate_progression_session_economy
    (бой -> лут при победе -> покупка -> победные очки -> левел-ап), но
    останавливается сразу по достижении `target_level` вместо фиксированного
    числа боёв. Возвращает инвентарь/золото/статы в момент этой остановки —
    "естественный" результат органической игры, не искусственно набранный."""
    stats = dict(sc.CHARACTER_BASE_STATS)
    unspent_points = sc.CHARACTER_STARTING_POOL
    total_points_spent = 0
    stats, unspent_points, total_points_spent = sc._spend_all_points(stat_policy, stats, unspent_points, total_points_spent)
    stats["hp_max"] = pr.calculate_hp_max(stats["vitality"])

    victory_points = 0
    level = 1
    gold = 0
    potions_small = 0
    potions_large = 0
    rng = random.Random(seed)
    fight_index = 0

    while level < target_level:
        fight_index += 1
        if fight_index > max_fights:
            raise RuntimeError(f"уровень {target_level} не достигнут за {max_fights} боёв (seed={seed})")

        enemy_name = sc.roll_enemy_encounter(rng, level)
        fight_result = sce.simulate_single_fight_economy(
            stats, sc.ENEMY_PRESETS[enemy_name], "always_fight", rng, potions_small, potions_large
        )
        potion_used = fight_result["potion_used"]
        if potion_used == "small":
            potions_small -= 1
        elif potion_used == "large":
            potions_large -= 1

        if fight_result["result"] == "victory":
            loot_name, loot_price = sce.roll_loot(enemy_name, rng)
            if loot_name != "nothing":
                gold += loot_price

        gold, potions_small, potions_large = sce.buy_potions(gold, potions_small, potions_large)

        reward = pr.calculate_battle_reward(fight_result["result"], enemy_name)
        old_points = victory_points
        victory_points += reward
        levels_gained = pr.calculate_levels_gained(old_points, victory_points)
        if levels_gained > 0:
            level += levels_gained
            unspent_points += pr.calculate_stat_points_gained(levels_gained, stat_points_per_level)
            stats, unspent_points, total_points_spent = sc._spend_all_points(
                stat_policy, stats, unspent_points, total_points_spent
            )
            stats["hp_max"] = pr.calculate_hp_max(stats["vitality"])

    return {
        "seed": seed,
        "fight_index": fight_index,
        "level_reached": level,  # может быть > target_level, если один бой перепрыгнул несколько уровней разом
        "gold": gold,
        "potions_small": potions_small,
        "potions_large": potions_large,
        "stats": dict(stats),
    }


def run_natural_stock_all_seeds(target_level, seeds, stat_policy, stat_points_per_level, max_fights) -> list:
    return [
        run_natural_stock_at_level(target_level, seed, stat_policy, stat_points_per_level, max_fights)
        for seed in seeds
    ]


def print_natural_stock_report(rows: list, target_level: int) -> None:
    print(f"\n=== Прогон 1: естественный запас зелий на входе в {target_level} уровень ===")
    header = f"{'seed':>6} {'бой №':>7} {'уровень':>8} {'малых':>6} {'больших':>8} {'золото':>8}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['seed']:>6} {r['fight_index']:>7} {r['level_reached']:>8} "
            f"{r['potions_small']:>6} {r['potions_large']:>8} {r['gold']:>8}"
        )
    print("-" * len(header))
    print(
        f"Среднее: малых={statistics.mean(r['potions_small'] for r in rows):.1f}, "
        f"больших={statistics.mean(r['potions_large'] for r in rows):.1f}, "
        f"бой №={statistics.mean(r['fight_index'] for r in rows):.1f}"
    )


# ---------------------------------------------------------------------------
# Статы N-го уровня — усреднены по трассе боя за боем (не по чекпоинтам,
# см. докстринг модуля — чекпоинты для одного уровня слишком редкие).
# ---------------------------------------------------------------------------


def compute_typical_level_stats(target_level: int, seeds=PROBE_SEEDS, policy: str = STAT_ALLOCATION_POLICY, session_fights: int = STATS_PROBE_SESSION_FIGHTS) -> tuple:
    """Как sb.compute_typical_level_9_10_stats, но для одного произвольного
    уровня и по полной трассе (trajectory), не по срезам раз в
    CHECKPOINT_INTERVAL боёв — см. докстринг модуля. Возвращает (статы,
    общее число точек, число точек по каждому seed) — последнее нужно,
    чтобы явно видеть, что все seed внесли вклад, а не 1-2 из пяти."""
    samples = []
    samples_per_seed = {}
    for seed in seeds:
        rng = random.Random(seed)
        checkpoint_rng = random.Random(seed + 1_000_000)
        trajectory, _checkpoints = sc.simulate_progression_session(
            session_fights, policy, rng, checkpoint_rng, pr.STAT_POINTS_PER_LEVEL
        )
        seed_samples = [t for t in trajectory if t["level"] == target_level]
        samples_per_seed[seed] = len(seed_samples)
        samples.extend(seed_samples)

    if not samples:
        raise RuntimeError(f"ни один seed из {seeds} не дал точку на уровне {target_level} за {session_fights} боёв")

    stats = {
        "strength": round(statistics.mean(s["stats"]["strength"] for s in samples)),
        "agility": round(statistics.mean(s["stats"]["agility"] for s in samples)),
        "luck": round(statistics.mean(s["stats"]["luck"] for s in samples)),
        "vitality": round(statistics.mean(s["stats"]["vitality"] for s in samples)),
    }
    stats["hp_max"] = pr.calculate_hp_max(stats["vitality"])
    return stats, len(samples), samples_per_seed


# ---------------------------------------------------------------------------
# Прогон 2 — win rate на статах N-го уровня против BOSS_PRESET, 3 сценария
# ---------------------------------------------------------------------------


def run_boss_scenarios(player_stats: dict, boss_stats: dict, scenarios: dict, seeds, fights_per_seed: int) -> dict:
    """`scenarios` — {label: (potions_small, potions_large)}. Каждый
    сценарий прогоняется по всем seed, результаты объединяются (pooled) в
    одну сводку на сценарий — тот же принцип, что и в
    scripts/simulate_boss_partial_stock.py."""
    summaries = {}
    for label, (small, large) in scenarios.items():
        results = []
        for seed in seeds:
            rng = random.Random(seed)
            results.extend(
                sb.run_boss_batch(player_stats, boss_stats, fights_per_seed, rng, small, large, unlimited_potions=True)
            )
        summaries[label] = {"potions_small": small, "potions_large": large, "summary": sb.summarize_boss(results)}
    return summaries


def print_boss_scenarios_report(summaries: dict, player_stats: dict, target_level: int) -> None:
    print(f"\n=== Прогон 2: win rate против финального босса на статах {target_level} уровня ===")
    print(f"Статы игрока: {player_stats}")
    print(f"Статы босса: {sb.BOSS_PRESET}")
    header = f"{'сценарий':<14} {'малых':>6} {'больших':>8} {'victory%':>9} {'defeat%':>9} {'rounds':>7}"
    print(header)
    print("-" * len(header))
    for label, entry in summaries.items():
        s = entry["summary"]
        print(
            f"{label:<14} {entry['potions_small']:>6} {entry['potions_large']:>8} "
            f"{s['outcome_percent']['victory']:9.1f} {s['outcome_percent']['defeat']:9.1f} {s['rounds_mean']:7.1f}"
        )


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def export_csv(natural_stock_rows: list, boss_summaries: dict, fights_per_seed: int, seeds, out_path: Path) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["# Прогон 1 — естественный запас на входе в уровень", TARGET_LEVEL])
        writer.writerow(["seed", "fight_index", "level_reached", "potions_small", "potions_large", "gold"])
        for r in natural_stock_rows:
            writer.writerow([r["seed"], r["fight_index"], r["level_reached"], r["potions_small"], r["potions_large"], r["gold"]])

        writer.writerow([])
        writer.writerow(["# Прогон 2 — win rate против босса", f"seeds={list(seeds)}", f"fights_per_seed={fights_per_seed}"])
        writer.writerow(["scenario", "potions_small", "potions_large", "victory_pct", "defeat_pct", "rounds_mean"])
        for label, entry in boss_summaries.items():
            s = entry["summary"]
            writer.writerow([
                label, entry["potions_small"], entry["potions_large"],
                round(s["outcome_percent"]["victory"], 2), round(s["outcome_percent"]["defeat"], 2),
                round(s["rounds_mean"], 2),
            ])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fights-per-seed", type=int, default=DEFAULT_FIGHTS_PER_SEED)
    return parser.parse_args()


def main():
    args = parse_args()

    natural_stock_rows = run_natural_stock_all_seeds(
        TARGET_LEVEL, PROBE_SEEDS, STAT_ALLOCATION_POLICY, pr.STAT_POINTS_PER_LEVEL, NATURAL_STOCK_MAX_FIGHTS
    )
    print_natural_stock_report(natural_stock_rows, TARGET_LEVEL)
    natural_small = round(statistics.mean(r["potions_small"] for r in natural_stock_rows))
    natural_large = round(statistics.mean(r["potions_large"] for r in natural_stock_rows))

    player_stats, sample_count, samples_per_seed = compute_typical_level_stats(TARGET_LEVEL)
    print(f"\nСтаты {TARGET_LEVEL} уровня (по {sample_count} точкам трассы, по seed: {samples_per_seed}): {player_stats}")

    scenarios = {
        "естественный": (natural_small, natural_large),
        "0 зелий": (0, 0),
        "полный 5+3": (ec.SMALL_POTION_CAP, ec.LARGE_POTION_CAP),
    }
    boss_summaries = run_boss_scenarios(player_stats, sb.BOSS_PRESET, scenarios, PROBE_SEEDS, args.fights_per_seed)
    print_boss_scenarios_report(boss_summaries, player_stats, TARGET_LEVEL)

    DATA_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = DATA_DIR / f"boss_early_unlock_{timestamp}.csv"
    export_csv(natural_stock_rows, boss_summaries, args.fights_per_seed, PROBE_SEEDS, out_path)
    print(f"\nCSV сохранён -> {out_path}")


if __name__ == "__main__":
    main()
