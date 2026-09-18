"""Тесты scripts/simulate_boss_early_unlock.py — оценка открытия босса
раньше, с 8 уровня (docs/notes.md)."""

import csv

import pytest

from core import progression as pr
from scripts import simulate_boss as sb
from scripts import simulate_boss_early_unlock as sbe


def test_run_natural_stock_at_level_reaches_target_level():
    result = sbe.run_natural_stock_at_level(
        target_level=3, seed=1, stat_policy="priority_str_vit",
        stat_points_per_level=pr.STAT_POINTS_PER_LEVEL, max_fights=200,
    )
    assert result["level_reached"] >= 3
    assert result["potions_small"] >= 0
    assert result["potions_large"] >= 0
    assert result["gold"] >= 0
    assert result["fight_index"] > 0


def test_run_natural_stock_at_level_raises_when_max_fights_exceeded():
    with pytest.raises(RuntimeError):
        sbe.run_natural_stock_at_level(
            target_level=8, seed=1, stat_policy="priority_str_vit",
            stat_points_per_level=pr.STAT_POINTS_PER_LEVEL, max_fights=1,
        )


def test_run_natural_stock_all_seeds_returns_one_row_per_seed():
    seeds = [1, 7, 42]
    rows = sbe.run_natural_stock_all_seeds(3, seeds, "priority_str_vit", pr.STAT_POINTS_PER_LEVEL, 200)
    assert [r["seed"] for r in rows] == seeds


def test_compute_typical_level_stats_matches_hp_max_formula():
    # Низкий уровень (3) вместо 8 — быстрее достигается за короткую сессию,
    # даёт больше точек трассы для короткого session_fights в тесте.
    stats, sample_count, samples_per_seed = sbe.compute_typical_level_stats(
        target_level=3, seeds=(1, 7), policy="priority_str_vit", session_fights=60
    )
    assert sample_count > 0
    assert stats["hp_max"] == pr.calculate_hp_max(stats["vitality"])
    for key in ("strength", "agility", "luck", "vitality"):
        assert stats[key] > 0
    assert set(samples_per_seed.keys()) == {1, 7}


def test_compute_typical_level_stats_raises_when_level_never_reached():
    # Уровень 50 недостижим за такую короткую сессию -> явная ошибка, не
    # тихий пустой результат.
    with pytest.raises(RuntimeError):
        sbe.compute_typical_level_stats(target_level=50, seeds=(1,), policy="priority_str_vit", session_fights=20)


def test_run_boss_scenarios_labels_each_scenario_with_its_potions():
    player_stats = {"strength": 8, "agility": 7, "luck": 6, "vitality": 8, "hp_max": 100}
    scenarios = {"a": (3, 0), "b": (0, 0), "c": (5, 3)}
    summaries = sbe.run_boss_scenarios(player_stats, sb.BOSS_PRESET, scenarios, seeds=(1, 7), fights_per_seed=20)

    assert set(summaries.keys()) == {"a", "b", "c"}
    assert summaries["a"]["potions_small"] == 3
    assert summaries["a"]["potions_large"] == 0
    assert summaries["c"]["summary"]["n"] == 40  # 2 seed x 20 боёв


def test_run_boss_scenarios_full_stash_never_worse_than_no_potions():
    player_stats = {"strength": 8, "agility": 7, "luck": 6, "vitality": 8, "hp_max": 100}
    scenarios = {"none": (0, 0), "full": (sb.FULL_STASH_SMALL_POTIONS, sb.FULL_STASH_LARGE_POTIONS)}
    summaries = sbe.run_boss_scenarios(player_stats, sb.BOSS_PRESET, scenarios, seeds=(1, 7, 42), fights_per_seed=100)

    assert (
        summaries["full"]["summary"]["outcome_percent"]["victory"]
        >= summaries["none"]["summary"]["outcome_percent"]["victory"]
    )


def test_export_csv_writes_both_sections(tmp_path):
    natural_stock_rows = [
        {"seed": 1, "fight_index": 99, "level_reached": 8, "potions_small": 1, "potions_large": 0, "gold": 18},
    ]
    boss_summaries = {
        "естественный": {"potions_small": 1, "potions_large": 0, "summary": {
            "outcome_percent": {"victory": 0.1, "defeat": 99.9, "player_fled": 0, "enemy_fled": 0}, "rounds_mean": 16.0,
            "n": 100, "potions_used_avg": 1.0,
        }},
    }
    out_path = tmp_path / "boss_early_unlock_test.csv"

    sbe.export_csv(natural_stock_rows, boss_summaries, fights_per_seed=100, seeds=(1,), out_path=out_path)

    with out_path.open(encoding="utf-8") as f:
        content = f.read()
    assert "Прогон 1" in content
    assert "Прогон 2" in content
    with out_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert any(row[:1] == ["1"] for row in rows if row)  # seed 1 из Прогона 1 присутствует
