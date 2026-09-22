"""Измеряет эффект смены формулы уворота (docs/combat_mechanics.md §4,
docs/notes.md п.60) — с кривой насыщения с жёстким потолком (`MAX_FACES`,
`round()`) на асимптотическую кривую без потолка (`floor()`, тот же
принцип, что у двойного удара §5) — на win rate игрока и мобов.

Метод: `core.combat_mechanics.resolve_strike` временно подменяется в
памяти этого процесса на копию со старой формулой уворота (контекстный
менеджер `_dodge_formula(old=True)`), затем гоняется СУЩЕСТВУЮЩАЯ
калибровочная инфраструктура (`scripts.simulate_combat`, `scripts.
simulate_boss`) без единой правки в них самих — подмена восстанавливается
сразу после выхода из блока `with`, даже при исключении. Ничего не пишет
ни в core/, ни в другие файлы scripts/ — только измерение в памяти.

Старая формула уворота реализуема без дублирования: `calculate_saturating_
success_faces` (core/combat_mechanics.py) никуда не делась — раньше
обслуживала и уворот, и побег, теперь только побег (§6), но как чистая
функция при тех же аргументах (max_faces=5, k, min_faces=1) считает
старую формулу уворота один в один.

ТОЛЬКО ИЗМЕРЕНИЕ — не трогает ENEMY_PRESETS/BOSS_PRESET/DODGE_K ни при
каком результате.

Запуск:
    python -m scripts.simulate_dodge_formula_change
"""

import contextlib
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
from core import progression as pr  # noqa: E402
from scripts import simulate_boss as sb  # noqa: E402
from scripts import simulate_combat as sc  # noqa: E402

OLD_DODGE_MAX_FACES = 5  # значение MAX_FACES, действовавшее до п.60
PROGRESSION_SESSION_FIGHTS = 100
PROGRESSION_ALLOCATION_POLICY = "priority_str_vit"
BOSS_FIGHTS_PER_SEED = 3000

FORMULA_LABELS = (("старая (потолок)", True), ("новая (асимптота)", False))


# ---------------------------------------------------------------------------
# Подмена формулы уворота
# ---------------------------------------------------------------------------


def _old_resolve_strike(
    attacker_strength,
    defender_agility,
    attack_roll,
    dodge_roll,
    dodge_k,
    dodge_min_faces=cm.DODGE_MIN_FACES_DEFAULT,
    power_attack=False,
):
    """Копия cm.resolve_strike — сигнатура идентична (drop-in замена через
    монки-патч), но уворот считается по старой формуле с потолком через
    cm.calculate_saturating_success_faces (см. докстринг модуля)."""
    attack_percent = (
        cm.resolve_power_attack_percent(attack_roll) if power_attack else cm.resolve_attack_percent(attack_roll)
    )
    if attack_percent is None:
        return cm.StrikeResult(missed=True, attack_percent=None, dodge_success_faces=None, dodged=None, damage=0.0)

    dodge_success_faces = cm.calculate_saturating_success_faces(
        defender_agility, max_faces=OLD_DODGE_MAX_FACES, k=dodge_k, min_faces=dodge_min_faces
    )
    dodged = cm.is_dodge_successful(dodge_roll, dodge_success_faces)
    if dodged:
        damage = 0.0
    elif power_attack:
        damage = round(attacker_strength * attack_percent / 100 * cm.POWER_ATTACK_DAMAGE_MULTIPLIER)
    else:
        damage = cm.calculate_damage(attacker_strength, attack_percent)
    return cm.StrikeResult(
        missed=False, attack_percent=attack_percent, dodge_success_faces=dodge_success_faces,
        dodged=dodged, damage=damage,
    )


@contextlib.contextmanager
def _dodge_formula(old: bool):
    """old=True -> cm.resolve_strike временно указывает на старую формулу
    уворота для всех модулей, импортировавших `combat_mechanics` как `cm`
    (общий объект модуля в sys.modules, подмена видна везде). Восстановление
    гарантировано даже при исключении внутри блока."""
    if not old:
        yield
        return
    original = cm.resolve_strike
    cm.resolve_strike = _old_resolve_strike
    try:
        yield
    finally:
        cm.resolve_strike = original


# ---------------------------------------------------------------------------
# Часть 3.1 — мышь/волк/кабан, single-mode
# ---------------------------------------------------------------------------


def run_single_mode_comparison(fights: int, seed: int) -> dict:
    results = {}
    for label, old in FORMULA_LABELS:
        rng = random.Random(seed)
        summaries = {}
        with _dodge_formula(old):
            for enemy_name in sc.ENCOUNTER_ORDER:
                batch = sc.run_batch(
                    enemy_name, sc.ENEMY_PRESETS[enemy_name], sc.PLAYER_STATS, fights, "always_fight", rng
                )
                summaries[enemy_name] = sc.summarize(batch, enemy_name)
        results[label] = summaries
    return results


def print_single_mode_comparison(results: dict, fights: int, seed: int) -> None:
    print(f"\n=== Часть 3.1: мышь/волк/кабан (single-mode, fights={fights}, seed={seed}) ===")
    header = f"{'моб':<8} {'формула':<20} {'victory%':>9} {'defeat%':>9} {'раунды':>8}"
    print(header)
    print("-" * len(header))
    for enemy_name in sc.ENCOUNTER_ORDER:
        for label, _old in FORMULA_LABELS:
            s = results[label][enemy_name]
            print(
                f"{enemy_name:<8} {label:<20} {s['outcome_percent']['victory']:9.1f} "
                f"{s['outcome_percent']['defeat']:9.1f} {s['rounds_mean']:8.1f}"
            )


# ---------------------------------------------------------------------------
# Часть 3.2 — progression-режим, 100 боёв × 5 seed
# ---------------------------------------------------------------------------


def run_progression_comparison(session_fights: int, seeds) -> dict:
    results = {}
    for label, old in FORMULA_LABELS:
        per_seed = []
        with _dodge_formula(old):
            for seed in seeds:
                rng = random.Random(seed)
                checkpoint_rng = random.Random(seed + 1_000_000)
                _trajectory, checkpoints = sc.simulate_progression_session(
                    session_fights, PROGRESSION_ALLOCATION_POLICY, rng, checkpoint_rng, pr.STAT_POINTS_PER_LEVEL
                )
                per_seed.append({"seed": seed, "checkpoints": checkpoints})
        results[label] = per_seed
    return results


def print_progression_comparison(results: dict, session_fights: int, seeds) -> None:
    print(
        f"\n=== Часть 3.2: progression ({session_fights} боёв × {len(seeds)} seed, "
        f"policy={PROGRESSION_ALLOCATION_POLICY}) — win rate на последнем чекпоинте ==="
    )
    header = f"{'seed':>6} {'формула':<20} {'уровень':>7} {'мышь%':>7} {'волк%':>7} {'кабан%':>7}"
    print(header)
    print("-" * len(header))
    for label, _old in FORMULA_LABELS:
        wolf_values, boar_values = [], []
        for entry in results[label]:
            cp = entry["checkpoints"][-1] if entry["checkpoints"] else None
            if cp is None:
                print(f"{entry['seed']:>6} {label:<20}   (нет контрольных точек)")
                continue
            print(
                f"{entry['seed']:>6} {label:<20} {cp['level']:>7} {cp['winrate_mouse']:>7.1f} "
                f"{cp['winrate_wolf']:>7.1f} {cp['winrate_boar']:>7.1f}"
            )
            wolf_values.append(cp["winrate_wolf"])
            boar_values.append(cp["winrate_boar"])
        if wolf_values:
            print(
                f"{'':>6} {label + ' (среднее)':<20} {'':>7} {'':>7} "
                f"{statistics.mean(wolf_values):>7.1f} {statistics.mean(boar_values):>7.1f}"
            )


# ---------------------------------------------------------------------------
# Часть 3.3 — босс, полный запас, с мощным ударом
# ---------------------------------------------------------------------------


def run_boss_comparison(fights_per_seed: int, seeds) -> tuple:
    # Статы игрока — один раз, под ТЕКУЩЕЙ (новой) формулой уворота, и
    # держатся одинаковыми для обоих прогонов ниже: изолируем именно эффект
    # формулы уворота НА САМ БОЙ С БОССОМ, не на путь до него по уровням.
    player_stats, sample_count = sb.compute_typical_level_9_10_stats()

    results = {}
    for label, old in FORMULA_LABELS:
        per_seed = []
        with _dodge_formula(old):
            for seed in seeds:
                rng = random.Random(seed)
                batch = sb.run_boss_batch(
                    player_stats, sb.BOSS_PRESET, fights_per_seed, rng,
                    potions_small=sb.FULL_STASH_SMALL_POTIONS, potions_large=sb.FULL_STASH_LARGE_POTIONS,
                    unlimited_potions=True, power_attack=True,
                )
                per_seed.append({"seed": seed, "summary": sb.summarize_boss(batch)})
        results[label] = per_seed
    return results, player_stats, sample_count


def print_boss_comparison(results: dict, player_stats: dict, sample_count: int, fights_per_seed: int, seeds) -> None:
    print(f'\n=== Часть 3.3: босс | "полный запас" (5+3) + мощный удар | fights/seed={fights_per_seed} ===')
    print(f"Статы игрока (типичный уровень 9-10, {sample_count} точек, формула не варьируется): {player_stats}")
    print(f"Статы босса: {sb.BOSS_PRESET}")

    header = f"{'seed':>6} {'формула':<20} {'victory%':>9} {'раунды':>8}"
    print(header)
    print("-" * len(header))
    for label, _old in FORMULA_LABELS:
        values = []
        for entry in results[label]:
            s = entry["summary"]
            values.append(s["outcome_percent"]["victory"])
            print(f"{entry['seed']:>6} {label:<20} {s['outcome_percent']['victory']:9.1f} {s['rounds_mean']:8.1f}")
        print(
            f"{'':>6} {label + ' (мин/макс/среднее)':<20} "
            f"{min(values):.1f}/{max(values):.1f}/{statistics.mean(values):.1f}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    single_results = run_single_mode_comparison(fights=5000, seed=42)
    print_single_mode_comparison(single_results, fights=5000, seed=42)

    progression_results = run_progression_comparison(PROGRESSION_SESSION_FIGHTS, sb.PROBE_SEEDS)
    print_progression_comparison(progression_results, PROGRESSION_SESSION_FIGHTS, sb.PROBE_SEEDS)

    boss_results, player_stats, sample_count = run_boss_comparison(BOSS_FIGHTS_PER_SEED, sb.PROBE_SEEDS)
    print_boss_comparison(boss_results, player_stats, sample_count, BOSS_FIGHTS_PER_SEED, sb.PROBE_SEEDS)


if __name__ == "__main__":
    main()
