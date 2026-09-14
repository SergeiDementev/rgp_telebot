"""Тесты scripts/simulate_combat.py: choose_stat_to_allocate."""

import pytest

from scripts import simulate_combat as sc


def test_choose_stat_round_robin_blind_rotation_by_points_spent():
    # Стартовые статы неравны (Удача=1, остальные=3) — ротация всё равно
    # идёт строго по ROTATION_ORDER, не подглядывая в текущие значения.
    stats = {"strength": 3, "agility": 3, "luck": 1, "vitality": 3}
    expected_sequence = [
        "strength", "agility", "luck", "vitality",
        "strength", "agility", "luck", "vitality",
    ]
    for total_points_spent, expected_stat in enumerate(expected_sequence):
        assert sc.choose_stat_to_allocate("round_robin", stats, total_points_spent) == expected_stat


def test_choose_stat_round_robin_does_not_pick_low_value_stat_out_of_turn():
    # Удача сильно ниже остальных — но на total_points_spent=0/1 ротация всё
    # равно называет strength/agility, а не "подтягивает" Удачу вне очереди.
    stats = {"strength": 10, "agility": 10, "luck": 1, "vitality": 10}
    assert sc.choose_stat_to_allocate("round_robin", stats, total_points_spent=0) == "strength"
    assert sc.choose_stat_to_allocate("round_robin", stats, total_points_spent=1) == "agility"


def test_choose_stat_priority_str_vit_before_target_picks_only_strength_or_vitality():
    stats = {"strength": 3, "agility": 3, "luck": 1, "vitality": 3}  # сумма 6 < 8
    stat = sc.choose_stat_to_allocate("priority_str_vit", stats, total_points_spent=0)
    assert stat in ("strength", "vitality")


def test_choose_stat_priority_str_vit_balances_the_lower_of_the_pair():
    stats = {"strength": 5, "agility": 3, "luck": 1, "vitality": 2}  # сумма 7 < 8, vitality отстаёт
    assert sc.choose_stat_to_allocate("priority_str_vit", stats, total_points_spent=0) == "vitality"


def test_choose_stat_priority_str_vit_rotates_all_four_after_target_reached():
    # После порога — не "заморозка" strength/vitality навсегда, а слепая
    # ротация ПО ВСЕМ ЧЕТЫРЁМ статам (ROTATION_ORDER), просто без приоритета.
    stats = {"strength": 4, "agility": 3, "luck": 1, "vitality": 4}  # сумма 8 >= target
    expected_sequence = ["strength", "agility", "luck", "vitality"]
    for offset, expected_stat in enumerate(expected_sequence):
        assert sc.choose_stat_to_allocate("priority_str_vit", stats, total_points_spent=offset) == expected_stat


def test_choose_stat_priority_str_vit_strength_and_vitality_keep_growing_after_target():
    # Регрессия: strength/vitality не замораживаются после прохождения порога —
    # на большом числе последующих allocate-вызовов оба продолжают расти.
    stats = {"strength": 4, "agility": 3, "luck": 1, "vitality": 4}
    strength_start, vitality_start = stats["strength"], stats["vitality"]
    for total_points_spent in range(40):
        stat = sc.choose_stat_to_allocate("priority_str_vit", stats, total_points_spent)
        stats[stat] += 1
    assert stats["strength"] > strength_start
    assert stats["vitality"] > vitality_start


def test_choose_stat_priority_agility_before_target_picks_agility():
    stats = {"strength": 3, "agility": 3, "luck": 1, "vitality": 3}  # agility=3 < 7
    assert sc.choose_stat_to_allocate("priority_agility", stats, total_points_spent=0) == "agility"


def test_choose_stat_priority_agility_rotates_remaining_three_after_target():
    stats = {"strength": 3, "agility": 7, "luck": 1, "vitality": 3}  # agility достигла цели
    assert sc.choose_stat_to_allocate("priority_agility", stats, total_points_spent=0) == "strength"
    assert sc.choose_stat_to_allocate("priority_agility", stats, total_points_spent=1) == "luck"
    assert sc.choose_stat_to_allocate("priority_agility", stats, total_points_spent=2) == "vitality"
    assert sc.choose_stat_to_allocate("priority_agility", stats, total_points_spent=3) == "strength"


def test_choose_stat_priority_luck_before_target_picks_luck():
    stats = {"strength": 3, "agility": 3, "luck": 1, "vitality": 3}  # luck=1 < 7
    assert sc.choose_stat_to_allocate("priority_luck", stats, total_points_spent=0) == "luck"


def test_choose_stat_priority_luck_rotates_remaining_three_after_target():
    stats = {"strength": 3, "agility": 3, "luck": 7, "vitality": 3}  # luck достигла цели
    assert sc.choose_stat_to_allocate("priority_luck", stats, total_points_spent=0) == "strength"
    assert sc.choose_stat_to_allocate("priority_luck", stats, total_points_spent=1) == "agility"
    assert sc.choose_stat_to_allocate("priority_luck", stats, total_points_spent=2) == "vitality"
    assert sc.choose_stat_to_allocate("priority_luck", stats, total_points_spent=3) == "strength"


def test_choose_stat_skip_agility_luck_never_picks_agility_or_luck():
    # Ловкость и Удача крайне низкие — но политика игнорирует значения вообще
    # и никогда их не выбирает, даже когда они сильно отстают.
    stats = {"strength": 10, "agility": 1, "luck": 1, "vitality": 10}
    picks = {sc.choose_stat_to_allocate("skip_agility_luck", stats, n) for n in range(10)}
    assert picks == {"strength", "vitality"}


def test_choose_stat_skip_agility_luck_blind_rotation_strength_vitality():
    stats = {"strength": 3, "agility": 3, "luck": 1, "vitality": 3}
    assert sc.choose_stat_to_allocate("skip_agility_luck", stats, total_points_spent=0) == "strength"
    assert sc.choose_stat_to_allocate("skip_agility_luck", stats, total_points_spent=1) == "vitality"
    assert sc.choose_stat_to_allocate("skip_agility_luck", stats, total_points_spent=2) == "strength"


def test_choose_stat_to_allocate_rejects_unknown_policy():
    stats = {"strength": 3, "agility": 3, "luck": 1, "vitality": 3}
    with pytest.raises(ValueError):
        sc.choose_stat_to_allocate("nonexistent_policy", stats, total_points_spent=0)


@pytest.mark.parametrize(
    "policy",
    ["round_robin", "priority_str_vit", "priority_agility", "priority_luck", "skip_agility_luck"],
)
def test_simulate_progression_session_runs_end_to_end_with_both_policies(policy):
    import random

    rng = random.Random(1)
    checkpoint_rng = random.Random(2)
    trajectory, checkpoints = sc.simulate_progression_session(
        session_fights=15, policy=policy, rng=rng, checkpoint_rng=checkpoint_rng
    )
    assert len(trajectory) == 15
    assert len(checkpoints) == 1  # один чекпоинт на 10-м бою для 15-боевой сессии
    checkpoint = checkpoints[0]
    for stat in ("strength", "agility", "luck", "vitality"):
        assert stat in checkpoint
        assert checkpoint[stat] >= 1
