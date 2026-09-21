"""Измеряет эффект "💥 Мощный удар" (docs/combat_mechanics.md §3a) на win
rate против финального босса.

Сценарий — тот же "с полным запасом" (5 малых + 3 больших зелья, без
лимита "раз за бой" — docs/notes.md п.39), что и в scripts/simulate_
boss.py: baseline (игрок всегда бьёт обычной атакой) vs "всегда мощный
удар" (§3a). По каждому из 5 PROBE_SEEDS отдельно + разброс (мин/макс/
среднее/медиана) — так же, как в прошлых боссовых прогонах (scripts/
simulate_boss_early_unlock.py и др.). Один и тот же seed используется для
обоих сценариев одного прогона (парное сравнение — та же последовательность
бросков инициативы/обстоятельства/etc. в начале боя, расхождение появляется
только там, где решение "обычная/мощная атака" реально меняет исход).

ТОЛЬКО ИЗМЕРЕНИЕ — не меняет sb.BOSS_PRESET и не трогает формулу мощного
удара в core/combat_mechanics.py, даже если итоговый winrate выйдет за
целевые 40-70%. Не расширяет scripts/simulate_boss.py сверх уже добавленного
параметра power_attack — переиспользует run_boss_batch/summarize_boss/
compute_typical_level_9_10_stats как есть.

Запуск:
    python -m scripts.simulate_boss_power_attack
    python -m scripts.simulate_boss_power_attack --fights-per-seed 5000
"""

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import random  # noqa: E402

from scripts import simulate_boss as sb  # noqa: E402

DEFAULT_FIGHTS_PER_SEED = 3000


def run_seed_comparison(player_stats: dict, boss_stats: dict, seeds, fights_per_seed: int) -> list:
    rows = []
    for seed in seeds:
        baseline_results = sb.run_boss_batch(
            player_stats, boss_stats, fights_per_seed, random.Random(seed),
            potions_small=sb.FULL_STASH_SMALL_POTIONS, potions_large=sb.FULL_STASH_LARGE_POTIONS,
            unlimited_potions=True, power_attack=False,
        )
        power_results = sb.run_boss_batch(
            player_stats, boss_stats, fights_per_seed, random.Random(seed),
            potions_small=sb.FULL_STASH_SMALL_POTIONS, potions_large=sb.FULL_STASH_LARGE_POTIONS,
            unlimited_potions=True, power_attack=True,
        )
        rows.append(
            {
                "seed": seed,
                "baseline": sb.summarize_boss(baseline_results),
                "power_attack": sb.summarize_boss(power_results),
            }
        )
    return rows


def print_report(rows: list, player_stats: dict, boss_stats: dict, fights_per_seed: int) -> None:
    print(f'\n=== Босс | "полный запас" (5+3, без лимита) | fights/seed={fights_per_seed} ===')
    print(f"Статы игрока (типичный уровень 9-10): {player_stats}")
    print(f"Статы босса: {boss_stats}")

    header = f"{'seed':>6} {'baseline%':>10} {'power%':>8} {'delta пп':>9} {'baseline раунды':>16} {'power раунды':>13}"
    print(header)
    print("-" * len(header))

    baseline_values, power_values = [], []
    for row in rows:
        b = row["baseline"]["outcome_percent"]["victory"]
        p = row["power_attack"]["outcome_percent"]["victory"]
        baseline_values.append(b)
        power_values.append(p)
        print(
            f"{row['seed']:>6} {b:>10.1f} {p:>8.1f} {p - b:>+9.1f} "
            f"{row['baseline']['rounds_mean']:>16.1f} {row['power_attack']['rounds_mean']:>13.1f}"
        )
    print("-" * len(header))

    print(f"\n{'сценарий':<14} {'мин':>7} {'макс':>7} {'среднее':>9} {'медиана':>9}")
    for label, values in (("baseline", baseline_values), ("power_attack", power_values)):
        print(
            f"{label:<14} {min(values):>7.1f} {max(values):>7.1f} "
            f"{statistics.mean(values):>9.1f} {statistics.median(values):>9.1f}"
        )
    print(
        f"\nSummary: среднее winrate {statistics.mean(baseline_values):.1f}% -> "
        f"{statistics.mean(power_values):.1f}% (delta {statistics.mean(power_values) - statistics.mean(baseline_values):+.1f} пп)"
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fights-per-seed", type=int, default=DEFAULT_FIGHTS_PER_SEED)
    return parser.parse_args()


def main():
    args = parse_args()
    player_stats, sample_count = sb.compute_typical_level_9_10_stats()
    print(f"Статы игрока (типичный уровень 9-10 по {len(sb.PROBE_SEEDS)} seed, {sample_count} точек-чекпоинтов): {player_stats}")

    rows = run_seed_comparison(player_stats, sb.BOSS_PRESET, sb.PROBE_SEEDS, args.fights_per_seed)
    print_report(rows, player_stats, sb.BOSS_PRESET, args.fights_per_seed)


if __name__ == "__main__":
    main()
