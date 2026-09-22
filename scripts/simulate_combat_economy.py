"""Симулятор экономики (лут/золото/зелья) ПОВЕРХ проверенного combat/
progression движка (docs/notes.md) — не заменяет scripts/simulate_combat.py,
а расширяет его для отдельного вопроса калибровки: как лут и зелья влияют
на прогрессию персонажа, изолированно от самого боевого ядра.

ЖЁСТКОЕ ОГРАНИЧЕНИЕ: core/combat_mechanics.py и core/progression.py не
меняются вообще — импортируются и вызываются как есть, как и в
simulate_combat.py. Экономика (лут, золото, зелья) — не часть игровой
боевой механики, это отдельный слой поверх неё.

Константы и чистые функции экономики (LOOT_TABLE, цены/капы зелий, выбор
зелья, покупка) живут в core/economy.py (docs/notes.md, п.30) — единый
источник для этого симулятора и для api/, не дублируются. Здесь только
переиспользуются (`from core import economy as ec`) плюс то, что специфично
именно для симулятора (авто-покупка без игрока — `buy_potions()`, ниже).

Что переиспользуется из scripts/simulate_combat.py (через `import ... as sc`,
без дублирования): _new_fighter, _fight_result, _wants_to_flee,
roll_enemy_encounter, _spend_all_points, choose_stat_to_allocate,
_run_checkpoint_probe, run_batch, все константы (ENEMY_PRESETS,
DODGE_K/DOUBLE_STRIKE_K/FLEE_MAX_FACES/FLEE_K/
FLEE_THRESHOLD_PERCENT/CIRCUMSTANCE_MODIFIER_PERCENT/ENCOUNTER_FACES_BY_
LEVEL_BAND через core.progression, CHARACTER_BASE_STATS/CHARACTER_STARTING_
POOL/CHECKPOINT_INTERVAL/CHECKPOINT_FIGHTS/ENCOUNTER_ORDER).

Единственное, что копируется, — control-flow цикла ходов
(`simulate_single_fight` -> `simulate_single_fight_economy`): экономике
нужно вставить новый шаг (исцеление зельем) посреди уже существующего
цикла, а сам simulate_combat.py трогать не хотим (см. ограничение выше).
Копия не переопределяет ни одной формулы — каждый под-расчёт по-прежнему
идёт через cm.* и sc._fight_result/sc._new_fighter/sc._wants_to_flee.
Важное следствие: когда зелий в инвентаре нет (potions_small=potions_large=0,
т.е. control-прогон без экономики), новый шаг не потребляет ни одного
дополнительного броска rng — контрольный прогон детерминированно идёт
той же последовательностью бросков, что и оригинальный движок, а значит
расхождение с экономикой в самом деле изолированное, а не побочный эффект
другого RNG-порядка.

Запуск (по умолчанию — ровно то, что описано в задаче):
    python scripts/simulate_combat_economy.py
    python scripts/simulate_combat_economy.py --session-fights-list 100,300 --seeds 1,7,42,100,2024
"""

import argparse
import csv
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # Windows-консоль по умолчанию не в UTF-8 — иначе кириллица ломается.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from core import combat_mechanics as cm  # noqa: E402
from core import economy as ec  # noqa: E402
from core import progression as pr  # noqa: E402
from scripts import simulate_combat as sc  # noqa: E402

# Реэкспорт констант из core/economy.py (единый источник, docs/notes.md
# п.30) — оставлены под старыми именами здесь, чтобы не трогать вызывающий
# код/тесты этого файла; значения всегда совпадают с core.economy, т.к. это
# просто ссылки на те же объекты, не копии.
LOOT_TABLE = ec.LOOT_TABLE
SMALL_POTION_HEAL_PERCENT = ec.SMALL_POTION_HEAL_PERCENT
LARGE_POTION_HEAL_PERCENT = ec.LARGE_POTION_HEAL_PERCENT
SMALL_POTION_PRICE = ec.SMALL_POTION_PRICE
LARGE_POTION_PRICE = ec.LARGE_POTION_PRICE
HEAL_TRIGGER_HP_PERCENT = ec.HEAL_TRIGGER_HP_PERCENT
SMALL_POTION_CAP = ec.SMALL_POTION_CAP
LARGE_POTION_CAP = ec.LARGE_POTION_CAP

# Граница "раннего этапа" для диагностики цены входа в экономику
# (docs/notes.md) — уровни 1-4, дальше считается "остальная игра".
EARLY_GAME_MAX_LEVEL = 4


# ---------------------------------------------------------------------------
# Один бой с экономикой — копия sc.simulate_single_fight с одним новым шагом.
# ---------------------------------------------------------------------------


def roll_loot(enemy_name: str, rng) -> tuple:
    """Бросок на лут — независимая операция ПОСЛЕ результата боя, не часть
    самого fight_result (аналогично тому, как обстоятельство в бою решается
    отдельным броском поверх уже вычисленной инициативы). Сам выбор — через
    core.economy.resolve_loot_drop (не бросает кубик сам, только трактует
    готовый roll 1-100 по кумулятивным границам LOOT_TABLE) — рандом
    (rng.randint) остаётся на стороне симулятора, как и для всех боевых
    бросков (core/ не содержит случайности)."""
    return ec.resolve_loot_drop(enemy_name, rng.randint(1, 100))


_choose_potion = ec.choose_potion_to_drink
_potion_heal_percent = ec.potion_heal_percent


def _maybe_drink_potion(attacker: dict) -> None:
    """Пьёт зелье, если HP критическое и лимит "раз за бой" ещё не исчерпан
    (docs/notes.md) — мутирует `attacker` на месте (hp, potions_small/large,
    potion_used, potion_used_this_battle). Не трогает rng — решение
    полностью детерминировано текущим состоянием, никакого броска не нужно
    (в отличие от боевых проверок, которые все идут через cm.*)."""
    if attacker["potion_used_this_battle"]:
        return
    if not ec.is_hp_at_or_below_heal_threshold(attacker["hp"], attacker["hp_max"]):
        return
    potion = ec.choose_potion_to_drink(attacker["potions_small"], attacker["potions_large"])
    if potion is None:
        return
    if potion == "large":
        attacker["potions_large"] -= 1
    else:
        attacker["potions_small"] -= 1
    attacker["hp"] = min(attacker["hp"] + ec.calculate_heal_amount(attacker["hp_max"], potion), attacker["hp_max"])
    attacker["potion_used"] = potion
    attacker["potion_used_this_battle"] = True


def buy_potions(gold: int, potions_small: int, potions_large: int) -> tuple:
    """Автопокупка сессии-симулятора (docs/notes.md) — здесь решение "что
    купить" принимает сама AI-сессия, не игрок кнопкой (в отличие от
    реального `POST /character/{id}/buy_potion`, где размер выбирает игрок
    явно) — поэтому эта функция остаётся в симуляторе, а не в core/economy.py
    (аналогия — choose_stat_to_allocate в simulate_combat.py). Условия
    капа/цены при этом не дублирует — переиспользует core.economy.
    check_can_buy_potion/buy_potion как есть: пробуем Большое, не
    получилось — Малое."""
    if ec.check_can_buy_potion(gold, potions_small, potions_large, "large") is None:
        return ec.buy_potion(gold, potions_small, potions_large, "large")
    if ec.check_can_buy_potion(gold, potions_small, potions_large, "small") is None:
        return ec.buy_potion(gold, potions_small, potions_large, "small")
    return gold, potions_small, potions_large


def simulate_single_fight_economy(
    player_stats: dict, enemy_stats: dict, policy: str, rng, potions_small: int, potions_large: int
) -> dict:
    """Копия sc.simulate_single_fight (см. docstring модуля — почему копия,
    а не правка оригинала) с одним новым шагом: исцеление зельем перед
    шагом 4 (проверка побега по HP) — если исцелился, порог побега мог уже
    не сработать, что и есть весь смысл зелья. Только для игрока (у бота
    зелий нет), максимум одно зелье за весь бой, приоритет — Большое."""
    player = sc._new_fighter(player_stats)
    enemy = sc._new_fighter(enemy_stats)
    player["potions_small"] = potions_small
    player["potions_large"] = potions_large
    player["potion_used"] = None
    player["potion_used_this_battle"] = False

    # 1. Инициатива (§9 шаг 1). Ничья -> перебросить.
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
        roller["strength"], circumstance_outcome, sc.CIRCUMSTANCE_MODIFIER_PERCENT
    )

    double_strikes = {"player": 0, "enemy": 0}
    flee_offers = 0

    # ЦИКЛ ХОДОВ (§9 шаги 4-7 + новый шаг "зелье" перед шагом 4).
    turn_order = (first_role, second_role)
    turns_taken = 0

    while True:
        attacker_role = turn_order[turns_taken % 2]
        defender_role = turn_order[(turns_taken + 1) % 2]
        attacker = player if attacker_role == "player" else enemy
        defender = player if defender_role == "player" else enemy

        # НОВЫЙ ШАГ: зелье исцеления. Только игрок, максимум раз за бой, до
        # проверки на побег — залеченный игрок может уже не быть под
        # порогом и не нуждаться в решении "сбежать/остаться".
        if attacker_role == "player":
            _maybe_drink_potion(attacker)

        # 4. Возможность побега по HP-порогу (§6).
        if not attacker["flee_right_used"] and cm.is_hp_at_or_below_flee_threshold(
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
                    fight_result["turns_taken"] = turns_taken
                    fight_result["potion_used"] = player["potion_used"]
                    return fight_result

        # 5. Проверка двойного удара (§5).
        ds_faces = cm.calculate_double_strike_success_faces(attacker["luck"], sc.DOUBLE_STRIKE_K)
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
                dodge_k=sc.DODGE_K,
            )
            defender["hp"] = max(defender["hp"] - strike.damage, 0)
            if defender["hp"] <= 0:
                turns_taken += 1
                result = "victory" if attacker_role == "player" else "defeat"
                fight_result = sc._fight_result(
                    result, turns_taken, player, enemy, double_strikes,
                    circumstance_outcome, circumstance_roller, flee_offers,
                )
                fight_result["turns_taken"] = turns_taken
                fight_result["potion_used"] = player["potion_used"]
                return fight_result

        # 7. Ход переходит другой стороне.
        turns_taken += 1


# ---------------------------------------------------------------------------
# Сессия: персонаж растёт от боя к бою, экономика — необязательный слой.
# ---------------------------------------------------------------------------


def simulate_progression_session_economy(
    session_fights: int,
    policy: str,
    rng,
    checkpoint_rng,
    stat_points_per_level: int,
    economy_enabled: bool,
) -> tuple:
    """Как sc.simulate_progression_session, плюс (если economy_enabled) лут
    после победы и покупка зелий после каждого боя. `economy_enabled=False`
    даёт контрольный прогон: инвентарь зелий всегда пуст, значит новый шаг
    в simulate_single_fight_economy никогда не срабатывает и не трогает
    rng — при одинаковом seed контрольный прогон идёт тем же потоком
    бросков, что и исходный движок, до первого момента, когда экономика
    реально меняет состояние боя (см. docstring модуля)."""
    stats = dict(sc.CHARACTER_BASE_STATS)
    unspent_points = sc.CHARACTER_STARTING_POOL
    total_points_spent = 0
    stats, unspent_points, total_points_spent = sc._spend_all_points(policy, stats, unspent_points, total_points_spent)
    stats["hp_max"] = pr.calculate_hp_max(stats["vitality"])

    victory_points = 0
    level = 1
    gold = 0
    potions_small = 0
    potions_large = 0
    trajectory = []
    checkpoints = []

    for fight_index in range(1, session_fights + 1):
        enemy_name = sc.roll_enemy_encounter(rng, level)

        potions_small_start = potions_small
        potions_large_start = potions_large

        fight_result = simulate_single_fight_economy(
            stats, sc.ENEMY_PRESETS[enemy_name], "always_fight", rng, potions_small, potions_large
        )

        potion_used = fight_result["potion_used"]
        if potion_used == "small":
            potions_small -= 1
        elif potion_used == "large":
            potions_large -= 1

        loot_dropped = None
        if economy_enabled and fight_result["result"] == "victory":
            loot_name, loot_price = roll_loot(enemy_name, rng)
            if loot_name != "nothing":
                loot_dropped = loot_name
                gold += loot_price

        if economy_enabled:
            gold, potions_small, potions_large = buy_potions(gold, potions_small, potions_large)

        reward = pr.calculate_battle_reward(fight_result["result"], enemy_name)
        old_points = victory_points
        victory_points += reward
        levels_gained = pr.calculate_levels_gained(old_points, victory_points)
        if levels_gained > 0:
            level += levels_gained
            unspent_points += pr.calculate_stat_points_gained(levels_gained, stat_points_per_level)
            stats, unspent_points, total_points_spent = sc._spend_all_points(
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
                "turns_taken": fight_result["turns_taken"],
                "stats": dict(stats),
                "loot_dropped": loot_dropped,
                "gold_balance_after": gold,
                "potions_owned_small": potions_small_start,
                "potions_owned_large": potions_large_start,
                "potion_used": potion_used or "none",
            }
        )

        if fight_index % sc.CHECKPOINT_INTERVAL == 0:
            winrates = sc._run_checkpoint_probe(stats, checkpoint_rng)
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
                    "gold_balance": gold,
                }
            )

    return trajectory, checkpoints


# ---------------------------------------------------------------------------
# Диагностика "цены входа" в экономику на раннем этапе (docs/notes.md) —
# гипотеза: на уровнях 1-4 дохода не хватает, чтобы зелья реально
# появлялись и использовались, экономика включается только позже.
# ---------------------------------------------------------------------------


def _avg_gold(rows: list):
    if not rows:
        return None
    return statistics.mean(r["gold_balance_after"] for r in rows)


def _first_potion_ownership_fight(trajectory: list):
    """Номер боя, на НАЧАЛО которого персонаж уже владеет хотя бы одним
    зельем (potions_owned_* — снимок "на начало боя", см. CSV_FIELDNAMES).
    None, если за всю сессию так и не появилось ни одного зелья."""
    for row in trajectory:
        if row["potions_owned_small"] > 0 or row["potions_owned_large"] > 0:
            return row["fight_index"]
    return None


def _potion_use_rate_wolf_boar(rows: list):
    """Доля боёв с волком/кабаном, где было использовано зелье — мышь не
    считаем, там HP редко падает настолько низко, чтобы зелье пригодилось."""
    relevant = [r for r in rows if r["enemy"] in ("wolf", "boar")]
    if not relevant:
        return None
    used = sum(1 for r in relevant if r["potion_used"] != "none")
    return 100 * used / len(relevant)


def print_early_game_diagnostics(per_seed_economy_trajectories: list, session_fights: int) -> None:
    """per_seed_economy_trajectories: [{"seed", "trajectory"}, ...] — только
    economy-вариант (у control золота/зелий нет вообще, метрики бессмысленны).
    Сравнивает ранний этап (уровни 1-EARLY_GAME_MAX_LEVEL) с остальной игрой
    по тем же трём метрикам, что и ручная диагностика: средний баланс
    золота, номер первого боя с зельем в инвентаре, доля боёв волк/кабан
    с использованным зельем."""
    print(
        f"\n=== Ранний этап (уровни 1-{EARLY_GAME_MAX_LEVEL}) vs остальная игра "
        f"| session-fights={session_fights} ==="
    )
    header = (
        f"{'seed':>6} {'gold@early':>11} {'gold@rest':>10} {'1й_бой_с_зельем':>16} "
        f"{'зелье%@early':>13} {'зелье%@rest':>12}"
    )
    print(header)
    print("-" * len(header))

    gold_early_values, first_fight_values, rate_early_values = [], [], []
    for entry in per_seed_economy_trajectories:
        trajectory = entry["trajectory"]
        early_rows = [r for r in trajectory if r["level"] <= EARLY_GAME_MAX_LEVEL]
        rest_rows = [r for r in trajectory if r["level"] > EARLY_GAME_MAX_LEVEL]

        gold_early = _avg_gold(early_rows)
        gold_rest = _avg_gold(rest_rows)
        first_fight = _first_potion_ownership_fight(trajectory)
        rate_early = _potion_use_rate_wolf_boar(early_rows)
        rate_rest = _potion_use_rate_wolf_boar(rest_rows)

        gold_early_str = f"{gold_early:.1f}" if gold_early is not None else "н/д"
        gold_rest_str = f"{gold_rest:.1f}" if gold_rest is not None else "н/д"
        first_fight_str = str(first_fight) if first_fight is not None else "не появилось"
        rate_early_str = f"{rate_early:.1f}" if rate_early is not None else "н/д"
        rate_rest_str = f"{rate_rest:.1f}" if rate_rest is not None else "н/д"

        print(
            f"{entry['seed']:>6} {gold_early_str:>11} {gold_rest_str:>10} {first_fight_str:>16} "
            f"{rate_early_str:>13} {rate_rest_str:>12}"
        )

        if gold_early is not None:
            gold_early_values.append(gold_early)
        if first_fight is not None:
            first_fight_values.append(first_fight)
        if rate_early is not None:
            rate_early_values.append(rate_early)

    if gold_early_values:
        print(
            f"\nСреднее по seed'ам: gold@early={statistics.mean(gold_early_values):.1f}  "
            f"1й_бой_с_зельем={statistics.mean(first_fight_values):.1f}  "
            f"зелье%@early={statistics.mean(rate_early_values):.1f}%"
        )


# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------


def print_progression_table_economy(checkpoints: list, label: str) -> None:
    header = (
        f"{'бой':>5} {'уровень':>7} {'мышь%':>7} {'волк%':>7} {'кабан%':>7} "
        f"{'str':>4} {'agi':>4} {'luck':>4} {'vit':>4} {'gold':>6}"
    )
    print(f"\n=== {label} — прогрессия по контрольным точкам (каждые {sc.CHECKPOINT_INTERVAL} боёв) ===")
    print(header)
    print("-" * len(header))
    for row in checkpoints:
        print(
            f"{row['fight_index']:>5} {row['level']:>7} "
            f"{row['winrate_mouse']:>7.1f} {row['winrate_wolf']:>7.1f} {row['winrate_boar']:>7.1f} "
            f"{row['strength']:>4} {row['agility']:>4} {row['luck']:>4} {row['vitality']:>4} {row['gold_balance']:>6}"
        )


def print_economy_vs_control_summary(per_seed: list, session_fights: int) -> None:
    """per_seed: список {"seed", "economy_checkpoint", "control_checkpoint"}
    (последняя контрольная точка каждого прогона) — сводка "рядом" для
    сравнения эффекта экономики изолированно от остального шума по seed'ам."""
    print(f"\n=== Экономика vs контроль | session-fights={session_fights} (последняя контрольная точка) ===")
    header = (
        f"{'seed':>6} {'ур.эк':>6} {'ур.контр':>9} "
        f"{'кабан%эк':>9} {'кабан%контр':>12} {'gold(эк)':>9}"
    )
    print(header)
    print("-" * len(header))
    for entry in per_seed:
        ec, cc = entry["economy_checkpoint"], entry["control_checkpoint"]
        if ec is None or cc is None:
            print(f"{entry['seed']:>6}   (нет контрольных точек — session-fights < {sc.CHECKPOINT_INTERVAL})")
            continue
        print(
            f"{entry['seed']:>6} {ec['level']:>6} {cc['level']:>9} "
            f"{ec['winrate_boar']:>9.1f} {cc['winrate_boar']:>12.1f} {ec['gold_balance']:>9}"
        )


CSV_FIELDNAMES = [
    "variant", "session_fights", "seed", "battle_number", "enemy_type", "result",
    "reward_points", "victory_points_after", "level_after", "turns_taken",
    "loot_dropped", "gold_balance_after", "potions_owned_small", "potions_owned_large", "potion_used",
]


def trajectory_to_csv_rows(trajectory: list, variant: str, session_fights: int, seed: int) -> list:
    rows = []
    for entry in trajectory:
        rows.append(
            {
                "variant": variant,
                "session_fights": session_fights,
                "seed": seed,
                "battle_number": entry["fight_index"],
                "enemy_type": entry["enemy"],
                "result": entry["result"],
                "reward_points": entry["reward"],
                "victory_points_after": entry["victory_points"],
                "level_after": entry["level"],
                "turns_taken": entry["turns_taken"],
                "loot_dropped": entry["loot_dropped"] or "",
                "gold_balance_after": entry["gold_balance_after"],
                "potions_owned_small": entry["potions_owned_small"],
                "potions_owned_large": entry["potions_owned_large"],
                "potion_used": entry["potion_used"],
            }
        )
    return rows


def save_combined_csv(rows: list, timestamp: str) -> Path:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / f"economy_playtest_{timestamp}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session-fights-list", type=str, default="100,300")
    parser.add_argument("--seeds", type=str, default="1,7,42,100,2024")
    parser.add_argument(
        "--allocation-policy",
        choices=["round_robin", "priority_str_vit", "priority_agility", "priority_luck", "skip_agility_luck"],
        default="priority_str_vit",
    )
    parser.add_argument("--stat-points-per-level", type=int, default=pr.STAT_POINTS_PER_LEVEL)
    return parser.parse_args()


def run_one(session_fights: int, seed: int, policy: str, stat_points_per_level: int, economy_enabled: bool) -> tuple:
    """Один полный прогон сессии (economy или control) — свежий rng с нуля
    от seed, независимый от других прогонов, чтобы прогоны с одинаковым
    seed были сравнимы (см. docstring модуля)."""
    rng = random.Random(seed)
    checkpoint_rng = random.Random(seed + 1_000_000)
    return simulate_progression_session_economy(
        session_fights, policy, rng, checkpoint_rng, stat_points_per_level, economy_enabled
    )


def main():
    args = parse_args()
    session_fights_list = [int(s.strip()) for s in args.session_fights_list.split(",")]
    seeds = [int(s.strip()) for s in args.seeds.split(",")]
    timestamp = time.strftime("%Y%m%dT%H%M%S")

    print(
        f"=== simulate_combat_economy | session-fights={session_fights_list} | seeds={seeds} "
        f"| allocation-policy={args.allocation_policy} | stat-points-per-level={args.stat_points_per_level} ==="
    )

    all_csv_rows = []

    for session_fights in session_fights_list:
        per_seed_summary = []
        per_seed_economy_trajectories = []
        for seed in seeds:
            print(f"\n--- session-fights={session_fights} seed={seed} ---")

            econ_trajectory, econ_checkpoints = run_one(
                session_fights, seed, args.allocation_policy, args.stat_points_per_level, economy_enabled=True
            )
            print_progression_table_economy(econ_checkpoints, f"Экономика (seed={seed})")
            sc.save_progression_results(econ_trajectory, econ_checkpoints, f"{timestamp}_economy_sf{session_fights}_seed{seed}")
            all_csv_rows.extend(trajectory_to_csv_rows(econ_trajectory, "economy", session_fights, seed))
            per_seed_economy_trajectories.append({"seed": seed, "trajectory": econ_trajectory})

            ctrl_trajectory, ctrl_checkpoints = run_one(
                session_fights, seed, args.allocation_policy, args.stat_points_per_level, economy_enabled=False
            )
            print_progression_table_economy(ctrl_checkpoints, f"Контроль без экономики (seed={seed})")
            sc.save_progression_results(ctrl_trajectory, ctrl_checkpoints, f"{timestamp}_control_sf{session_fights}_seed{seed}")
            all_csv_rows.extend(trajectory_to_csv_rows(ctrl_trajectory, "control", session_fights, seed))

            per_seed_summary.append(
                {
                    "seed": seed,
                    "economy_checkpoint": econ_checkpoints[-1] if econ_checkpoints else None,
                    "control_checkpoint": ctrl_checkpoints[-1] if ctrl_checkpoints else None,
                }
            )

        print_economy_vs_control_summary(per_seed_summary, session_fights)
        print_early_game_diagnostics(per_seed_economy_trajectories, session_fights)

    out_path = save_combined_csv(all_csv_rows, timestamp)
    print(f"\nОбъединённый CSV (все прогоны, {len(all_csv_rows)} строк) сохранён: {out_path}")


if __name__ == "__main__":
    main()
