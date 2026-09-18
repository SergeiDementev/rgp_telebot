"""Форма кривой win rate против финального босса по ПРОМЕЖУТОЧНЫМ запасам
зелий (docs/notes.md) — дополняет scripts/simulate_boss.py, который
откалиброван только на двух крайних точках (0 зелий / полный запас 5+3).
Отдельный файл, не смешан с simulate_boss.py (её докстринг: "не трогаем",
чтобы не задеть уже согласованную калибровку) — переиспользует оттуда
(`sb`) статы игрока/босса и саму механику одного боя как есть, здесь
только цикл по комбинациям запаса + сводка/CSV.

Правило "без лимита 'зелье раз за бой'" в бою с боссом не меняется и не
специфично для какой-то одной точки — это реальное правило игры
(docs/notes.md, п.39), применяется одинаково ко всем комбинациям ниже,
включая нулевой запас (там оно просто не успевает сработать).

Сценарий 1 — win rate по 10 комбинациям запаса зелий (включая обе уже
откалиброванные крайние точки — 0/0 и 5/3, как контроль совпадения с
scripts/simulate_boss.py). Каждая комбинация прогоняется по тем же 5 seed,
что и в остальных калибровках сессии, --fights боёв на seed — итоги
seed'ов объединяются (pooled) в одну сводку на комбинацию, чтобы получить
большую устойчивую выборку на каждой точке, а не 5 маленьких.

Сценарий 2 — для комбинации "полный запас" (5 малых + 3 больших): среди
только ПРОИГРАННЫХ попыток (result="defeat") — сколько зелий по размерам
реально израсходовано в среднем, и какая доля проигрышей приходится на
"инвентарь исчерпан полностью" против "погиб раньше, чем допил всё".
Переиспользует боевые результаты той же (5, 3)-комбинации из сценария 1,
не прогоняет бои повторно.

Запуск:
    python -m scripts.simulate_boss_partial_stock
    python -m scripts.simulate_boss_partial_stock --fights 3000
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

from scripts import simulate_boss as sb  # noqa: E402
from scripts import simulate_combat as sc  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

DEFAULT_FIGHTS_PER_SEED = 2000  # ×5 seed = 10000 боёв на комбинацию (single-mode устойчивость)

# Комбинации запаса зелий для сценария 1 — по порядку, как в задаче. Обе
# крайние точки (0,0) и (5,3) — контроль совпадения с scripts/simulate_boss.py.
POTION_STOCK_COMBINATIONS = (
    (0, 0),
    (2, 0),
    (4, 0),
    (5, 0),
    (0, 1),
    (0, 2),
    (0, 3),
    (2, 1),
    (3, 2),
    (5, 3),
)

FULL_STASH_COMBINATION = (sb.FULL_STASH_SMALL_POTIONS, sb.FULL_STASH_LARGE_POTIONS)  # (5, 3)


# ---------------------------------------------------------------------------
# Сценарий 1 — win rate по частичному запасу
# ---------------------------------------------------------------------------


def run_combination(player_stats, boss_stats, potions_small, potions_large, fights_per_seed, seeds) -> list:
    """Бои по одной комбинации запаса, объединённые (pooled) по всем seed —
    та же идея, что sb.compute_typical_level_9_10_stats() делает для статов
    прогрессии: несколько независимых потоков rng вместо одного длинного,
    итог устойчивее к конкретному seed."""
    results = []
    for seed in seeds:
        rng = random.Random(seed)
        results.extend(
            sb.run_boss_batch(
                player_stats, boss_stats, fights_per_seed, rng,
                potions_small=potions_small, potions_large=potions_large, unlimited_potions=True,
            )
        )
    return results


def run_stock_curve(player_stats, boss_stats, fights_per_seed, seeds) -> dict:
    """Возвращает {(small, large): {"results": [...], "summary": {...}}} по
    каждой комбинации из POTION_STOCK_COMBINATIONS — сырые результаты
    сохраняются (не только сводка), чтобы сценарий 2 мог переиспользовать
    бои по (5, 3) без повторного прогона."""
    by_combination = {}
    for small, large in POTION_STOCK_COMBINATIONS:
        results = run_combination(player_stats, boss_stats, small, large, fights_per_seed, seeds)
        by_combination[(small, large)] = {"results": results, "summary": sb.summarize_boss(results)}
    return by_combination


def print_stock_curve(by_combination: dict, fights_per_seed: int, seeds) -> None:
    total_fights = fights_per_seed * len(seeds)
    print(f"\n=== Сценарий 1: win rate по частичному запасу зелий (без лимита 'раз за бой') ===")
    print(f"seeds={list(seeds)}, fights/seed={fights_per_seed}, итого боёв на комбинацию={total_fights}")
    header = (
        f"{'малых':>6} {'больших':>8} {'victory%':>9} {'defeat%':>9} {'fled%':>7} "
        f"{'rounds':>7} {'зелий/бой':>10}"
    )
    print(header)
    print("-" * len(header))
    for small, large in POTION_STOCK_COMBINATIONS:
        summary = by_combination[(small, large)]["summary"]
        fled_pct = summary["outcome_percent"]["player_fled"] + summary["outcome_percent"]["enemy_fled"]
        print(
            f"{small:>6} {large:>8} {summary['outcome_percent']['victory']:9.1f} "
            f"{summary['outcome_percent']['defeat']:9.1f} {fled_pct:7.1f} "
            f"{summary['rounds_mean']:7.1f} {summary['potions_used_avg']:10.2f}"
        )


# ---------------------------------------------------------------------------
# Сценарий 2 — расход зелий в проигранных попытках (комбинация 5+3)
# ---------------------------------------------------------------------------


def summarize_defeat_potion_usage(results: list, small_cap: int, large_cap: int) -> dict:
    defeats = [r for r in results if r["result"] == "defeat"]
    if not defeats:
        return {"n_fights": len(results), "n_defeats": 0}

    small_used = [r["potions_small_used"] for r in defeats]
    large_used = [r["potions_large_used"] for r in defeats]
    fully_drained = sum(
        1 for r in defeats if r["potions_small_used"] >= small_cap and r["potions_large_used"] >= large_cap
    )
    return {
        "n_fights": len(results),
        "n_defeats": len(defeats),
        "defeat_rate_pct": 100 * len(defeats) / len(results),
        "small_used_avg": statistics.mean(small_used),
        "large_used_avg": statistics.mean(large_used),
        "small_used_max": max(small_used),
        "large_used_max": max(large_used),
        "fully_drained_pct": 100 * fully_drained / len(defeats),
        "died_with_leftover_pct": 100 * (len(defeats) - fully_drained) / len(defeats),
    }


def print_defeat_potion_usage(summary: dict, small_cap: int, large_cap: int) -> None:
    print(f"\n=== Сценарий 2: расход зелий в ПРОИГРАННЫХ попытках (запас {small_cap}+{large_cap}, без лимита) ===")
    if summary["n_defeats"] == 0:
        print("Проигранных боёв не было в этой выборке — нечего анализировать.")
        return
    print(f"Проигрышей: {summary['n_defeats']} из {summary['n_fights']} ({summary['defeat_rate_pct']:.1f}%)")
    print(
        f"Малых зелий до поражения:   среднее={summary['small_used_avg']:.2f} "
        f"(макс={summary['small_used_max']} из {small_cap})"
    )
    print(
        f"Больших зелий до поражения: среднее={summary['large_used_avg']:.2f} "
        f"(макс={summary['large_used_max']} из {large_cap})"
    )
    print(f"Запас израсходован полностью: {summary['fully_drained_pct']:.1f}% проигрышей")
    print(f"Погиб с остатком зелий:       {summary['died_with_leftover_pct']:.1f}% проигрышей")


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def export_csv(by_combination: dict, defeat_summary: dict, fights_per_seed: int, seeds, out_path: Path) -> None:
    fieldnames = [
        "potions_small", "potions_large", "seeds", "fights_per_seed", "fights_total",
        "victory_pct", "defeat_pct", "player_fled_pct", "enemy_fled_pct", "rounds_mean", "potions_used_avg",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for small, large in POTION_STOCK_COMBINATIONS:
            summary = by_combination[(small, large)]["summary"]
            writer.writerow({
                "potions_small": small,
                "potions_large": large,
                "seeds": ";".join(str(s) for s in seeds),
                "fights_per_seed": fights_per_seed,
                "fights_total": fights_per_seed * len(seeds),
                "victory_pct": round(summary["outcome_percent"]["victory"], 2),
                "defeat_pct": round(summary["outcome_percent"]["defeat"], 2),
                "player_fled_pct": round(summary["outcome_percent"]["player_fled"], 2),
                "enemy_fled_pct": round(summary["outcome_percent"]["enemy_fled"], 2),
                "rounds_mean": round(summary["rounds_mean"], 2),
                "potions_used_avg": round(summary["potions_used_avg"], 3),
            })

        # Сценарий 2 — отдельный блок строк в том же файле (комментарии
        # начинаются с "#", чтобы не сбивать парсер CSV с фиксированными
        # колонками выше, при этом данные остаются в одном файле, как просили).
        f.write("\n# Сценарий 2 — расход зелий в проигранных попытках (запас 5+3, без лимита)\n")
        if defeat_summary["n_defeats"] == 0:
            f.write("# нет проигранных боёв в выборке\n")
        else:
            f.write(f"# n_fights={defeat_summary['n_fights']}, n_defeats={defeat_summary['n_defeats']}, "
                    f"defeat_rate_pct={defeat_summary['defeat_rate_pct']:.2f}\n")
            f.write(f"# small_used_avg={defeat_summary['small_used_avg']:.3f}, "
                    f"large_used_avg={defeat_summary['large_used_avg']:.3f}\n")
            f.write(f"# fully_drained_pct={defeat_summary['fully_drained_pct']:.2f}, "
                    f"died_with_leftover_pct={defeat_summary['died_with_leftover_pct']:.2f}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fights", type=int, default=DEFAULT_FIGHTS_PER_SEED, help="боёв на seed на комбинацию")
    parser.add_argument(
        "--seeds", type=str, default=",".join(str(s) for s in sb.PROBE_SEEDS),
        help='seed через запятую, напр. "1,7,42,100,2024"',
    )
    return parser.parse_args()


def main():
    args = parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]

    player_stats, sample_count = sb.compute_typical_level_9_10_stats()
    print(f"Статы игрока (типичный уровень {sb.PROBE_TARGET_LEVELS}, {sample_count} точек-чекпоинтов): {player_stats}")
    print(f"Статы босса: {sb.BOSS_PRESET}")

    by_combination = run_stock_curve(player_stats, sb.BOSS_PRESET, args.fights, seeds)
    print_stock_curve(by_combination, args.fights, seeds)

    full_stash_results = by_combination[FULL_STASH_COMBINATION]["results"]
    defeat_summary = summarize_defeat_potion_usage(
        full_stash_results, sb.FULL_STASH_SMALL_POTIONS, sb.FULL_STASH_LARGE_POTIONS
    )
    print_defeat_potion_usage(defeat_summary, sb.FULL_STASH_SMALL_POTIONS, sb.FULL_STASH_LARGE_POTIONS)

    DATA_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = DATA_DIR / f"boss_partial_stock_{timestamp}.csv"
    export_csv(by_combination, defeat_summary, args.fights, seeds, out_path)
    print(f"\nCSV сохранён -> {out_path}")


if __name__ == "__main__":
    main()
