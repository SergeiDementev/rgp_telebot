"""Тесты scripts/simulate_boss_recovery_farm.py — время рефарма зелий
после поражения от финального босса (docs/notes.md, пп.43-44)."""

import csv
import random

import pytest

from core import progression as pr
from scripts import simulate_boss_recovery_farm as sbr

PLAYER_STATS = {"strength": 9, "agility": 8, "luck": 7, "vitality": 9, "hp_max": 110}


# ---------------------------------------------------------------------------
# Вариант 1 — статы заморожены (п.43)
# ---------------------------------------------------------------------------


def test_farm_until_full_stash_frozen_stats_reaches_small_caps_and_conserves_gold():
    # Небольшие капы вместо реальных 5/3 (docs/notes.md) — держит тест
    # быстрым, сама логика цикла (бой -> лут -> покупка -> проверка капа)
    # та же самая, что и с реальными капами.
    rng = random.Random(1)
    result = sbr.farm_until_full_stash_frozen_stats(
        PLAYER_STATS, sbr.FARM_LEVEL, rng, small_cap=1, large_cap=1, max_fights=500
    )
    assert result["fights"] > 0
    assert result["victories"] + result["defeats"] + result["fled"] == result["fights"]
    assert result["final_gold"] >= 0
    assert result["final_level"] == sbr.FARM_LEVEL  # статы/уровень не меняются вообще


def test_farm_until_full_stash_frozen_stats_raises_when_max_fights_exceeded():
    # Капы заведомо недостижимы за 1 бой -> RuntimeError, не тихий обрыв.
    rng = random.Random(1)
    with pytest.raises(RuntimeError):
        sbr.farm_until_full_stash_frozen_stats(
            PLAYER_STATS, sbr.FARM_LEVEL, rng, small_cap=5, large_cap=3, max_fights=1
        )


def test_run_all_seeds_frozen_returns_one_row_per_seed():
    seeds = [1, 7, 42]
    rows = sbr.run_all_seeds_frozen(PLAYER_STATS, sbr.FARM_LEVEL, seeds, small_cap=1, large_cap=1, max_fights=500)
    assert [r["seed"] for r in rows] == seeds
    for row in rows:
        assert row["fights"] > 0


# ---------------------------------------------------------------------------
# Вариант 2 — статы растут (п.44)
# ---------------------------------------------------------------------------


def test_farm_until_full_stash_with_progression_reaches_caps_and_may_level_up():
    rng = random.Random(1)
    starting_vp = pr.calculate_level_threshold(sbr.STARTING_LEVEL)
    result = sbr.farm_until_full_stash_with_progression(
        PLAYER_STATS, sbr.STARTING_LEVEL, starting_vp, sbr.STAT_ALLOCATION_POLICY, rng,
        pr.STAT_POINTS_PER_LEVEL, small_cap=1, large_cap=1, max_fights=200,
    )
    assert result["fights"] > 0
    assert result["victories"] + result["defeats"] + result["fled"] == result["fights"]
    assert result["final_gold"] >= 0
    assert result["final_level"] >= sbr.STARTING_LEVEL  # растущие статы -> уровень не может упасть


def test_farm_until_full_stash_with_progression_raises_when_max_fights_exceeded():
    rng = random.Random(1)
    starting_vp = pr.calculate_level_threshold(sbr.STARTING_LEVEL)
    with pytest.raises(RuntimeError):
        sbr.farm_until_full_stash_with_progression(
            PLAYER_STATS, sbr.STARTING_LEVEL, starting_vp, sbr.STAT_ALLOCATION_POLICY, rng,
            pr.STAT_POINTS_PER_LEVEL, small_cap=5, large_cap=3, max_fights=1,
        )


def test_farm_until_full_stash_with_progression_needs_far_fewer_fights_than_frozen():
    # Главная проверка регрессии сценария (docs/notes.md, п.44) — с ростом
    # статов набрать реальные капы (5+3) должно получаться на порядок
    # быстрее, чем с заморозкой (там уходило сотни боёв, см. п.43).
    seed = 1
    starting_vp = pr.calculate_level_threshold(sbr.STARTING_LEVEL)

    rng_progression = random.Random(seed)
    progression_result = sbr.farm_until_full_stash_with_progression(
        PLAYER_STATS, sbr.STARTING_LEVEL, starting_vp, sbr.STAT_ALLOCATION_POLICY, rng_progression,
        pr.STAT_POINTS_PER_LEVEL, small_cap=5, large_cap=3, max_fights=200,
    )

    assert progression_result["fights"] < 100  # ожидание — близко к ~28-32, не сотни


def test_run_all_seeds_with_progression_returns_one_row_per_seed():
    seeds = [1, 7, 42]
    starting_vp = pr.calculate_level_threshold(sbr.STARTING_LEVEL)
    rows = sbr.run_all_seeds_with_progression(
        PLAYER_STATS, sbr.STARTING_LEVEL, starting_vp, sbr.STAT_ALLOCATION_POLICY, seeds,
        pr.STAT_POINTS_PER_LEVEL, small_cap=1, large_cap=1, max_fights=200,
    )
    assert [r["seed"] for r in rows] == seeds
    for row in rows:
        assert row["fights"] > 0


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_export_csv_writes_both_variants_with_labels(tmp_path):
    frozen_rows = [{"seed": 1, "fights": 800, "victories": 700, "defeats": 10, "fled": 90, "final_gold": 0, "final_level": 9}]
    progression_rows = [{"seed": 1, "fights": 30, "victories": 28, "defeats": 0, "fled": 2, "final_gold": 10, "final_level": 15}]
    out_path = tmp_path / "boss_recovery_farm_test.csv"

    sbr.export_csv(frozen_rows, progression_rows, out_path)

    with out_path.open(encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert len(csv_rows) == 2
    assert csv_rows[0]["variant"] == "frozen_stats"
    assert csv_rows[0]["fights"] == "800"
    assert csv_rows[1]["variant"] == "with_progression"
    assert csv_rows[1]["fights"] == "30"
