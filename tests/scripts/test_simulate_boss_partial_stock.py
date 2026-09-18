"""Тесты scripts/simulate_boss_partial_stock.py — кривая win rate по
частичному запасу зелий + расход зелий в проигранных попытках (docs/notes.md)."""

import csv

import pytest

from scripts import simulate_boss as sb
from scripts import simulate_boss_partial_stock as sbp

PLAYER_STATS = {"hp_max": 110, "strength": 9, "agility": 8, "luck": 7}


def test_run_combination_pools_results_across_all_seeds():
    seeds = [1, 7]
    fights_per_seed = 20
    results = sbp.run_combination(PLAYER_STATS, sb.BOSS_PRESET, 5, 3, fights_per_seed, seeds)
    assert len(results) == fights_per_seed * len(seeds)


def test_run_stock_curve_covers_every_combination():
    seeds = [1, 7]
    by_combination = sbp.run_stock_curve(PLAYER_STATS, sb.BOSS_PRESET, 20, seeds)
    assert set(by_combination.keys()) == set(sbp.POTION_STOCK_COMBINATIONS)
    for (small, large), entry in by_combination.items():
        assert len(entry["results"]) == 20 * len(seeds)
        assert entry["summary"]["n"] == 20 * len(seeds)


def test_run_stock_curve_no_prep_combination_never_wins():
    # (0, 0) — контрольная точка, без зелий шанс победить над боссом
    # пренебрежимо мал (та же логика, что и в scripts/simulate_boss.py).
    seeds = [1, 7, 42]
    by_combination = sbp.run_stock_curve(PLAYER_STATS, sb.BOSS_PRESET, 50, seeds)
    summary = by_combination[(0, 0)]["summary"]
    assert summary["outcome_percent"]["victory"] < 5.0


def test_run_stock_curve_full_stash_beats_partial_stash():
    # Форма кривой должна быть монотонной по общему объёму лечения —
    # полный запас (5,3) не может проигрывать по victory% любой частичной
    # комбинации из того же набора.
    seeds = [1, 7, 42]
    by_combination = sbp.run_stock_curve(PLAYER_STATS, sb.BOSS_PRESET, 100, seeds)
    full_victory = by_combination[sbp.FULL_STASH_COMBINATION]["summary"]["outcome_percent"]["victory"]
    for combo, entry in by_combination.items():
        if combo == sbp.FULL_STASH_COMBINATION:
            continue
        assert entry["summary"]["outcome_percent"]["victory"] <= full_victory


def _fake_result(result: str, small_used: int, large_used: int) -> dict:
    return {"result": result, "potions_small_used": small_used, "potions_large_used": large_used}


def test_summarize_defeat_potion_usage_computes_averages_and_drain_rate():
    results = [
        _fake_result("victory", 5, 3),  # не входит в выборку — не defeat
        _fake_result("defeat", 5, 3),  # запас исчерпан полностью
        _fake_result("defeat", 5, 3),  # запас исчерпан полностью
        _fake_result("defeat", 2, 1),  # погиб раньше, с остатком
    ]
    summary = sbp.summarize_defeat_potion_usage(results, small_cap=5, large_cap=3)

    assert summary["n_fights"] == 4
    assert summary["n_defeats"] == 3
    assert summary["small_used_avg"] == pytest.approx((5 + 5 + 2) / 3)
    assert summary["large_used_avg"] == pytest.approx((3 + 3 + 1) / 3)
    assert summary["fully_drained_pct"] == pytest.approx(2 / 3 * 100)
    assert summary["died_with_leftover_pct"] == pytest.approx(1 / 3 * 100)


def test_summarize_defeat_potion_usage_handles_no_defeats():
    results = [_fake_result("victory", 1, 1), _fake_result("player_fled", 0, 0)]
    summary = sbp.summarize_defeat_potion_usage(results, small_cap=5, large_cap=3)
    assert summary["n_defeats"] == 0
    assert summary["n_fights"] == 2


def test_export_csv_writes_one_row_per_combination_and_defeat_summary_block(tmp_path):
    seeds = [1, 7]
    by_combination = sbp.run_stock_curve(PLAYER_STATS, sb.BOSS_PRESET, 20, seeds)
    defeat_summary = sbp.summarize_defeat_potion_usage(
        by_combination[sbp.FULL_STASH_COMBINATION]["results"], sb.FULL_STASH_SMALL_POTIONS, sb.FULL_STASH_LARGE_POTIONS
    )
    out_path = tmp_path / "boss_partial_stock_test.csv"

    sbp.export_csv(by_combination, defeat_summary, 20, seeds, out_path)

    assert out_path.exists()
    with out_path.open(encoding="utf-8") as f:
        content = f.read()
    assert "# Сценарий 2" in content

    with out_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#") and line.strip()))
    assert len(rows) == len(sbp.POTION_STOCK_COMBINATIONS)
    combos_in_csv = {(int(r["potions_small"]), int(r["potions_large"])) for r in rows}
    assert combos_in_csv == set(sbp.POTION_STOCK_COMBINATIONS)
