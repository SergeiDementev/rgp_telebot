"""Тесты scripts/simulate_boss.py — калибровка финального босса (docs/notes.md)."""

import random

import pytest

from core import progression as pr
from scripts import simulate_boss as sb


@pytest.fixture(scope="module")
def typical_player_stats():
    # module-scope — дорогая (гоняет 5×150 боёв движка), детерминированная
    # (фиксированные PROBE_SEEDS), безопасно считать один раз на весь файл.
    stats, sample_count = sb.compute_typical_level_9_10_stats()
    return stats, sample_count


def test_compute_typical_level_9_10_stats_matches_hp_max_formula(typical_player_stats):
    stats, sample_count = typical_player_stats
    assert sample_count > 0
    assert stats["hp_max"] == pr.calculate_hp_max(stats["vitality"])
    for key in ("strength", "agility", "luck", "vitality"):
        assert stats[key] > 0


def test_compute_typical_level_9_10_stats_is_deterministic(typical_player_stats):
    # Те же seed -> тот же прогон движка -> те же статы, без рандома в самой
    # агрегации (среднее по чекпоинтам, посчитанным детерминированным rng).
    stats_1, _ = typical_player_stats
    stats_2, _count = sb.compute_typical_level_9_10_stats()
    assert stats_1 == stats_2


def _fighter(hp, hp_max, potions_small=0, potions_large=0):
    return {
        "hp": hp,
        "hp_max": hp_max,
        "potions_small": potions_small,
        "potions_large": potions_large,
        "potions_used_count": 0,
        "potions_small_used": 0,
        "potions_large_used": 0,
    }


def test_maybe_drink_potion_unlimited_ignores_once_per_battle_limit():
    attacker = _fighter(hp=10, hp_max=100, potions_small=0, potions_large=2)
    sb._maybe_drink_potion_unlimited(attacker)
    assert attacker["potions_used_count"] == 1
    assert attacker["potions_large"] == 1
    assert attacker["potions_large_used"] == 1
    assert attacker["potions_small_used"] == 0

    attacker["hp"] = 10  # снова критично на следующем ходу
    sb._maybe_drink_potion_unlimited(attacker)
    assert attacker["potions_used_count"] == 2  # второй раз за бой — можно, лимита нет
    assert attacker["potions_large"] == 0
    assert attacker["potions_large_used"] == 2


def test_maybe_drink_potion_unlimited_does_nothing_above_threshold():
    attacker = _fighter(hp=50, hp_max=100, potions_small=1, potions_large=1)
    sb._maybe_drink_potion_unlimited(attacker)
    assert attacker["potions_used_count"] == 0


def test_maybe_drink_potion_unlimited_does_nothing_without_potions():
    attacker = _fighter(hp=5, hp_max=100, potions_small=0, potions_large=0)
    sb._maybe_drink_potion_unlimited(attacker)
    assert attacker["potions_used_count"] == 0
    assert attacker["hp"] == 5


def test_simulate_single_fight_vs_boss_runs_without_error():
    player_stats = {"hp_max": 110, "strength": 9, "agility": 8, "luck": 7}
    rng = random.Random(5)
    for _ in range(300):
        result = sb.simulate_single_fight_vs_boss(
            player_stats, sb.BOSS_PRESET, "always_fight", rng,
            potions_small=sb.FULL_STASH_SMALL_POTIONS, potions_large=sb.FULL_STASH_LARGE_POTIONS,
            unlimited_potions=True,
        )
        assert "result" in result
        assert result["potions_used_count"] >= 0
        assert result["potions_small_used"] + result["potions_large_used"] == result["potions_used_count"]


def test_unlimited_potions_scenario_uses_more_potions_than_limited_scenario():
    # Прямое сравнение — ради чего вообще снимается лимит в сценарии "с
    # полным запасом" (задача): без лимита должно расходоваться заметно
    # больше зелий за бой, чем с обычным лимитом (максимум 1).
    player_stats = {"hp_max": 110, "strength": 9, "agility": 8, "luck": 7}

    rng_unlimited = random.Random(11)
    unlimited_results = [
        sb.simulate_single_fight_vs_boss(
            player_stats, sb.BOSS_PRESET, "always_fight", rng_unlimited,
            sb.FULL_STASH_SMALL_POTIONS, sb.FULL_STASH_LARGE_POTIONS, unlimited_potions=True,
        )
        for _ in range(200)
    ]
    rng_limited = random.Random(12)
    limited_results = [
        sb.simulate_single_fight_vs_boss(
            player_stats, sb.BOSS_PRESET, "always_fight", rng_limited,
            sb.FULL_STASH_SMALL_POTIONS, sb.FULL_STASH_LARGE_POTIONS, unlimited_potions=False,
        )
        for _ in range(200)
    ]

    assert max(r["potions_used_count"] for r in limited_results) <= 1
    unlimited_avg = sum(r["potions_used_count"] for r in unlimited_results) / len(unlimited_results)
    limited_avg = sum(r["potions_used_count"] for r in limited_results) / len(limited_results)
    assert unlimited_avg > limited_avg


@pytest.mark.parametrize("seed", [1, 100])
def test_boss_preset_hits_target_win_rate_ranges(typical_player_stats, seed):
    # Регрессия на саму калибровку (docs/notes.md) — если кто-то поменяет
    # BOSS_PRESET или константы боя/зелий, тест сразу укажет, что диапазоны
    # больше не сходятся. n=800 — компромисс между стабильностью % и
    # скоростью теста (полный прогон в скрипте использует 3000-5000, тут
    # маржа у обоих сценариев широкая — ~0% при потолке 5%, ~44% в
    # середине диапазона 40-70% — n поменьше всё равно не даёт ложных срабатываний).
    player_stats, _count = typical_player_stats

    rng_a = random.Random(seed)
    summary_no_prep = sb.summarize_boss(
        sb.run_boss_batch(player_stats, sb.BOSS_PRESET, 800, rng_a, potions_small=0, potions_large=0, unlimited_potions=False)
    )
    assert 0 <= summary_no_prep["outcome_percent"]["victory"] <= 5

    rng_b = random.Random(seed + 1)
    summary_full_stash = sb.summarize_boss(
        sb.run_boss_batch(
            player_stats, sb.BOSS_PRESET, 800, rng_b,
            potions_small=sb.FULL_STASH_SMALL_POTIONS, potions_large=sb.FULL_STASH_LARGE_POTIONS, unlimited_potions=True,
        )
    )
    assert 40 <= summary_full_stash["outcome_percent"]["victory"] <= 70


# ---------------------------------------------------------------------------
# ENEMY_CAN_FLEE — босс никогда не убегает, игрок не ограничен вообще
# ---------------------------------------------------------------------------


def test_enemy_can_flee_defaults_to_true_for_unlisted_types():
    assert sb.ENEMY_CAN_FLEE.get("mouse", True) is True
    assert sb.ENEMY_CAN_FLEE.get("wolf", True) is True
    assert sb.ENEMY_CAN_FLEE.get("some_future_enemy_type", True) is True
    assert sb.ENEMY_CAN_FLEE["boss"] is False


def test_boss_never_flees_even_at_critical_hp(typical_player_stats):
    # Прямая проверка эффекта: очень слабый босс (лёгкая, быстрая победа
    # игрока не нужна — наоборот, хотим ЧАСТО видеть боссу критическое HP,
    # но result никогда не должен быть "enemy_fled").
    player_stats, _count = typical_player_stats
    weak_boss = {"hp_max": 300, "strength": 1, "agility": 0, "luck": 10}  # огромный luck -> много попыток на побег, если бы они были разрешены
    rng = random.Random(21)
    results = sb.run_boss_batch(player_stats, weak_boss, 500, rng, potions_small=0, potions_large=0, unlimited_potions=False)
    assert all(r["result"] != "enemy_fled" for r in results)


def test_non_boss_enemy_type_can_still_flee_in_principle(typical_player_stats):
    # Сам механизм пропуска шага завязан на enemy_type, не захардкожен на
    # "boss" — тот же "слабый противник" сетап, что и в тесте выше (там он
    # действительно доводит противника до критического HP), но с типом,
    # не перечисленным в ENEMY_CAN_FLEE (значит True по умолчанию) —
    # enemy_fled должен оставаться возможным.
    player_stats, _count = typical_player_stats
    weak_boss = {"hp_max": 300, "strength": 1, "agility": 0, "luck": 10}
    rng = random.Random(21)
    results = [
        sb.simulate_single_fight_vs_boss(
            player_stats, weak_boss, "always_fight", rng,
            potions_small=0, potions_large=0, unlimited_potions=False, enemy_type="wolf",
        )
        for _ in range(500)
    ]
    assert any(r["result"] == "enemy_fled" for r in results)
