"""Время рефарма запаса зелий ПОСЛЕ поражения от финального босса (docs/
notes.md) — отдельная метрика от "время пути с 1 до полного запаса"
(~28-32 боя, тот замер шёл от уровня 1 с растущими статами по ходу
обычной progression-сессии).

Два варианта в этом файле:

  - `farm_until_full_stash_frozen_stats` (п.43, первая версия) — статы
    ЗАМОРОЖЕНЫ на типичном 9-10 уровне навсегда, персонаж не прогрессирует
    дальше во время фарма. Дала ~852.6 боя в среднем — на порядок больше
    ожидания, с огромным разбросом между seed (97-1671). Причина (не баг,
    проверено трассировкой золота): таблица встреч 9-10 уровня на 60%
    состоит из кабана (голый winrate на этих статах без зелий — 77.9%,
    поражение 12.8%), и без роста статов доход почти целиком уходит на
    подлечивание, а не на накопление резерва.
  - `farm_until_full_stash_with_progression` (п.44, эта версия — уточнение
    по замечанию плейтестера) — статы РАСТУТ по мере фарма, как в реальной
    игре: поражение от босса не откатывает персонажа, только сбрасывает
    gold/potions_small/potions_large до нуля (docs/notes.md, п.36/41 —
    сброс происходит только по явному "Начать заново" после ПОБЕДЫ, не
    после поражения). "Инъекция" стартового состояния — те же типичные
    9-10-уровневые статы/уровень/победные очки, что и в замороженной
    версии, но дальше буквально тот же цикл, что и в
    sce.simulate_progression_session_economy (левелап через
    pr.calculate_levels_gained/calculate_stat_points_gained + sc.
    _spend_all_points), просто с другой стартовой точкой и с остановкой по
    условию "оба капа заполнены", а не по фиксированному числу боёв.

Оба варианта переиспользуют scripts/simulate_boss.py (только статы для
стартовой точки) и scripts/simulate_combat_economy.py/simulate_combat.py
(сам бой, лут, покупка, таблица встреч, левел-ап) как есть — ни один из
трёх файлов не менялся.

Запуск:
    python -m scripts.simulate_boss_recovery_farm
    python -m scripts.simulate_boss_recovery_farm --seeds 1,7,42,100,2024 --max-fights 2000
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
from scripts import simulate_combat as sc  # noqa: E402
from scripts import simulate_combat_economy as sce  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Статы игрока сразу после поражения от босса — заданы явно (тот же порядок
# величины, что и scripts/simulate_boss.py::compute_typical_level_9_10_stats()
# по 5 seed прогрессии). Сумма статов (9+8+7+9=33) точно соответствует
# уровню 10 при чистом расходе очков (15 стартовых + 2×9 уровней-апов от
# 1 до 10 = 33, см. STARTING_STAT_POOL/STAT_POINTS_PER_LEVEL) — стартовый
# уровень/победные очки ниже выбраны согласованно с этим.
POST_DEFEAT_PLAYER_STATS = {"strength": 9, "agility": 8, "luck": 7, "vitality": 9, "hp_max": 110}
FARM_LEVEL = 9  # для "замороженной" версии -> 10/30/60 мышь/волк/кабан (плато, 9 и 10 дают то же самое)

STARTING_LEVEL = 10
STAT_ALLOCATION_POLICY = "priority_str_vit"  # тот же policy, что и в остальных калибровках сессии

DEFAULT_SEEDS = (1, 7, 42, 100, 2024)  # те же 5 seed, что и во всех остальных калибровках сессии
DEFAULT_MAX_FIGHTS = 2000  # защитный потолок для "замороженной" версии (наблюдался максимум 1671)
DEFAULT_MAX_FIGHTS_PROGRESSION = 200  # с ростом статов ожидается число, близкое к ~28-32


# ---------------------------------------------------------------------------
# Вариант 1 (п.43) — статы заморожены навсегда
# ---------------------------------------------------------------------------


def farm_until_full_stash_frozen_stats(
    player_stats: dict, level: int, rng, small_cap: int, large_cap: int, max_fights: int
) -> dict:
    """Гоняет обычные (не боссовые) бои — мышь/волк/кабан по таблице встреч
    уровня `level` — начиная с 0 золота и 0 зелий, пока инвентарь не
    достигнет капа по обоим размерам разом. Статы/уровень не меняются
    вообще. Кидает RuntimeError, если не уложился в `max_fights`."""
    gold = 0
    potions_small = 0
    potions_large = 0
    fights = 0
    victories = 0
    defeats = 0
    fled = 0

    while not (potions_small >= small_cap and potions_large >= large_cap):
        fights += 1
        if fights > max_fights:
            raise RuntimeError(
                f"не удалось набрать полный запас за {max_fights} боёв "
                f"(потолок --max-fights, статы {player_stats})"
            )

        enemy_name = sc.roll_enemy_encounter(rng, level)
        fight_result = sce.simulate_single_fight_economy(
            player_stats, sc.ENEMY_PRESETS[enemy_name], "always_fight", rng, potions_small, potions_large
        )

        potion_used = fight_result["potion_used"]
        if potion_used == "small":
            potions_small -= 1
        elif potion_used == "large":
            potions_large -= 1

        if fight_result["result"] == "victory":
            victories += 1
            loot_name, loot_price = sce.roll_loot(enemy_name, rng)
            if loot_name != "nothing":
                gold += loot_price
        elif fight_result["result"] == "defeat":
            defeats += 1
        else:  # player_fled/enemy_fled — не должно случаться при policy="always_fight", но не молчим
            fled += 1

        gold, potions_small, potions_large = sce.buy_potions(gold, potions_small, potions_large)

    return {
        "fights": fights,
        "victories": victories,
        "defeats": defeats,
        "fled": fled,
        "final_gold": gold,
        "final_level": level,
    }


# ---------------------------------------------------------------------------
# Вариант 2 (п.44) — обычная прогрессия, только с "инъекцией" сброшенных
# gold/potions в стартовую точку вместо уровня 1.
# ---------------------------------------------------------------------------


def farm_until_full_stash_with_progression(
    starting_stats: dict,
    starting_level: int,
    starting_victory_points: int,
    stat_policy: str,
    rng,
    stat_points_per_level: int,
    small_cap: int,
    large_cap: int,
    max_fights: int,
) -> dict:
    """Буквально тот же цикл, что sce.simulate_progression_session_economy
    (бой -> лут при победе -> покупка -> начисление победных очков ->
    левел-ап при пересечении порога -> sc._spend_all_points), только:
      - стартует не с уровня 1/базовых статов, а с уже переданных
        `starting_stats`/`starting_level`/`starting_victory_points`
        (типичные статы после боя с боссом, а не персонаж с нуля);
      - gold/potions_small/potions_large стартуют с нуля в любом случае —
        это и есть "сброс" после поражения (docs/notes.md, п.36/41: сама
        победа над боссом сбрасывает персонажа целиком через "Начать
        заново", поражение — нет, оно только опустошает то, что было
        потрачено в этом заходе);
      - останавливается по условию "оба капа заполнены", а не по
        фиксированному числу боёв."""
    stats = dict(starting_stats)
    unspent_points = 0
    total_points_spent = 0
    level = starting_level
    victory_points = starting_victory_points
    gold = 0
    potions_small = 0
    potions_large = 0
    fights = 0
    victories = 0
    defeats = 0
    fled = 0

    while not (potions_small >= small_cap and potions_large >= large_cap):
        fights += 1
        if fights > max_fights:
            raise RuntimeError(
                f"не удалось набрать полный запас за {max_fights} боёв "
                f"(потолок --max-fights, стартовые статы {starting_stats})"
            )

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
            victories += 1
            loot_name, loot_price = sce.roll_loot(enemy_name, rng)
            if loot_name != "nothing":
                gold += loot_price
        elif fight_result["result"] == "defeat":
            defeats += 1
        else:
            fled += 1

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
        "fights": fights,
        "victories": victories,
        "defeats": defeats,
        "fled": fled,
        "final_gold": gold,
        "final_level": level,
    }


# ---------------------------------------------------------------------------
# Прогон по всем seed
# ---------------------------------------------------------------------------


def run_all_seeds_frozen(player_stats, level, seeds, small_cap, large_cap, max_fights) -> list:
    rows = []
    for seed in seeds:
        rng = random.Random(seed)
        result = farm_until_full_stash_frozen_stats(player_stats, level, rng, small_cap, large_cap, max_fights)
        rows.append({"seed": seed, **result})
    return rows


def run_all_seeds_with_progression(
    starting_stats, starting_level, starting_victory_points, stat_policy, seeds,
    stat_points_per_level, small_cap, large_cap, max_fights,
) -> list:
    rows = []
    for seed in seeds:
        rng = random.Random(seed)
        result = farm_until_full_stash_with_progression(
            starting_stats, starting_level, starting_victory_points, stat_policy, rng,
            stat_points_per_level, small_cap, large_cap, max_fights,
        )
        rows.append({"seed": seed, **result})
    return rows


# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------


def print_report(label: str, rows: list, small_cap: int, large_cap: int) -> None:
    fights_list = [r["fights"] for r in rows]
    print(f"\n=== {label}: 0 -> {small_cap} малых + {large_cap} больших ===")
    header = f"{'seed':>6} {'боёв':>6} {'побед':>6} {'поражений':>10} {'ур. на конец':>13} {'золото на конец':>16}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['seed']:>6} {r['fights']:>6} {r['victories']:>6} {r['defeats']:>10} "
            f"{r['final_level']:>13} {r['final_gold']:>16}"
        )
    print("-" * len(header))
    print(
        f"Боёв до полного запаса: среднее={statistics.mean(fights_list):.1f}, "
        f"мин={min(fights_list)}, макс={max(fights_list)}"
    )


def print_comparison(frozen_rows: list, progression_rows: list) -> None:
    frozen_mean = statistics.mean(r["fights"] for r in frozen_rows)
    progression_mean = statistics.mean(r["fights"] for r in progression_rows)
    print("\n=== Сравнение трёх замеров ===")
    print(f"{'сценарий':<45} {'боёв (среднее)':>15}")
    print("-" * 62)
    print(f"{'путь с 1 уровня (исходный замер)':<45} {'~28-32':>15}")
    print(f"{'рефарм, статы заморожены (docs/notes.md п.43)':<45} {frozen_mean:>15.1f}")
    print(f"{'рефарм, статы растут (docs/notes.md п.44)':<45} {progression_mean:>15.1f}")


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def export_csv(frozen_rows: list, progression_rows: list, out_path: Path) -> None:
    fieldnames = ["variant", "seed", "fights", "victories", "defeats", "fled", "final_level", "final_gold"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in frozen_rows:
            writer.writerow({"variant": "frozen_stats", **row})
        for row in progression_rows:
            writer.writerow({"variant": "with_progression", **row})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=str, default=",".join(str(s) for s in DEFAULT_SEEDS))
    parser.add_argument("--max-fights", type=int, default=DEFAULT_MAX_FIGHTS, help="потолок для 'заморожен' варианта")
    parser.add_argument(
        "--max-fights-progression", type=int, default=DEFAULT_MAX_FIGHTS_PROGRESSION,
        help="потолок для варианта с ростом статов",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    small_cap, large_cap = ec.SMALL_POTION_CAP, ec.LARGE_POTION_CAP
    starting_victory_points = pr.calculate_level_threshold(STARTING_LEVEL)

    frozen_rows = run_all_seeds_frozen(
        POST_DEFEAT_PLAYER_STATS, FARM_LEVEL, seeds, small_cap, large_cap, args.max_fights
    )
    print_report("Рефарм зелий после поражения от босса — статы ЗАМОРОЖЕНЫ (docs/notes.md, п.43)", frozen_rows, small_cap, large_cap)

    progression_rows = run_all_seeds_with_progression(
        POST_DEFEAT_PLAYER_STATS, STARTING_LEVEL, starting_victory_points, STAT_ALLOCATION_POLICY,
        seeds, pr.STAT_POINTS_PER_LEVEL, small_cap, large_cap, args.max_fights_progression,
    )
    print_report("Рефарм зелий после поражения от босса — статы РАСТУТ (docs/notes.md, п.44)", progression_rows, small_cap, large_cap)

    print_comparison(frozen_rows, progression_rows)

    DATA_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = DATA_DIR / f"boss_recovery_farm_{timestamp}.csv"
    export_csv(frozen_rows, progression_rows, out_path)
    print(f"\nCSV сохранён -> {out_path}")


if __name__ == "__main__":
    main()
