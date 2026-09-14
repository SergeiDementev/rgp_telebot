"""Тесты core/progression.py по docs/gameplay_loop_mvp.md."""

from datetime import datetime, timedelta

import pytest

from core import progression as pr


# ---------------------------------------------------------------------------
# 1. Уровни — threshold(N), границы перехода, скачок через несколько уровней
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "level,expected_threshold",
    [
        (1, 0),
        (2, 10),
        (3, 30),
        (4, 60),
        (5, 100),
    ],
)
def test_calculate_level_threshold_matches_doc_example(level, expected_threshold):
    assert pr.calculate_level_threshold(level) == expected_threshold


@pytest.mark.parametrize(
    "victory_points,expected_level",
    [
        (9, 1),    # на 1 очко меньше порога уровня 2 — уровень ещё не сменился
        (10, 2),   # ровно на пороге — уровень уже сменился
        (29, 2),   # на 1 очко меньше порога уровня 3
        (30, 3),   # ровно на пороге уровня 3
    ],
)
def test_calculate_level_for_points_boundary_is_inclusive(victory_points, expected_level):
    assert pr.calculate_level_for_points(victory_points) == expected_level


def test_calculate_levels_gained_can_skip_several_levels_at_once():
    # Награда за кабана (15 очков) может сразу перепрыгнуть с уровня 1 (8 очков)
    # через порог уровня 2 (10) и уровня 3 (30) — если очков хватает, до уровня 3.
    assert pr.calculate_levels_gained(old_points=8, new_points=35) == 2
    assert pr.calculate_level_for_points(8) == 1
    assert pr.calculate_level_for_points(35) == 3


@pytest.mark.parametrize(
    "old_points,new_points,expected_gained",
    [
        (5, 9, 0),    # прирост, не достигающий порога
        (9, 10, 1),   # прирост ровно до порога — засчитывается
        (10, 10, 0),  # без прироста — новых уровней нет
    ],
)
def test_calculate_levels_gained_boundaries(old_points, new_points, expected_gained):
    assert pr.calculate_levels_gained(old_points, new_points) == expected_gained


def test_points_to_next_level_matches_doc_mockup():
    # §5, мокап "Нет свободных очков": 6 очков Здоровья уже даёт уровень с
    # порогом 60 (уровень 4); до уровня 5 (порог 100) остаётся 100-86=14 очков,
    # как в примере "(до след. уровня: 14 победных очков)".
    assert pr.calculate_level_for_points(86) == 4
    assert pr.points_to_next_level(86) == 14


# ---------------------------------------------------------------------------
# 2. Регенерация HP — get_current_hp / time_to_full_hp
# ---------------------------------------------------------------------------


def test_get_current_hp_zero_elapsed_time_stays_unchanged():
    moment = datetime(2026, 1, 1, 12, 0, 0)
    assert pr.get_current_hp(hp_current=40, hp_max=60, last_update_at=moment, now=moment) == 40


def test_get_current_hp_exact_regeneration_for_given_elapsed_time():
    last = datetime(2026, 1, 1, 12, 0, 0)
    now = last + timedelta(seconds=15)
    assert pr.get_current_hp(hp_current=40, hp_max=60, last_update_at=last, now=now) == 55


def test_get_current_hp_caps_at_hp_max_for_large_elapsed_time():
    last = datetime(2026, 1, 1, 12, 0, 0)
    now = last + timedelta(hours=1)  # 3600 секунд — намного больше недостающих HP
    assert pr.get_current_hp(hp_current=40, hp_max=60, last_update_at=last, now=now) == 60


def test_get_current_hp_negative_elapsed_time_does_not_reduce_hp():
    # Если "сейчас" оказалось раньше last_update_at (рассинхронизация часов),
    # HP не должен уменьшаться — регенерация не может идти назад.
    last = datetime(2026, 1, 1, 12, 0, 30)
    now = last - timedelta(seconds=10)
    assert pr.get_current_hp(hp_current=40, hp_max=60, last_update_at=last, now=now) == 40


def test_time_to_full_hp_normal_case():
    assert pr.time_to_full_hp(hp_current=40, hp_max=60) == 20


def test_time_to_full_hp_already_full():
    assert pr.time_to_full_hp(hp_current=60, hp_max=60) == 0


def test_time_to_full_hp_above_max_returns_zero():
    assert pr.time_to_full_hp(hp_current=65, hp_max=60) == 0


# ---------------------------------------------------------------------------
# 3. Стат Здоровье -> HP_max
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vitality,expected_hp_max",
    [
        (0, 20),
        (3, 50),   # §2: стартовая база (Здоровье=3) в мокапе создания персонажа
        (5, 70),   # §5: мокап прокачки, "Здоровье: 5 (HP max: 70)"
        (6, 80),   # §5: после +1 к Здоровью, "Здоровье: 6 (HP max: 80)"
    ],
)
def test_calculate_hp_max_matches_doc_mockups(vitality, expected_hp_max):
    assert pr.calculate_hp_max(vitality) == expected_hp_max


def test_hp_current_is_not_touched_when_vitality_increases():
    # §3: "HP_current не меняется — то есть процент заполнения HP-бара после
    # прокачки Здоровья падает. Это осознанное решение, не баг."
    # calculate_hp_max вообще не принимает hp_current — растёт только hp_max.
    hp_current = 45.0

    hp_max_before = pr.calculate_hp_max(vitality=5)
    hp_max_after = pr.calculate_hp_max(vitality=6)

    assert hp_max_before == 70
    assert hp_max_after == 80
    assert hp_current == 45.0  # ни один вызов calculate_hp_max его не менял

    fill_percent_before = hp_current / hp_max_before
    fill_percent_after = hp_current / hp_max_after
    assert fill_percent_after < fill_percent_before  # доля заполнения падает


# ---------------------------------------------------------------------------
# 4. Награды по типу моба и по исходу боя
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "enemy_type,expected_reward",
    [
        ("mouse", 1),
        ("wolf", 5),
        ("boar", 15),
    ],
)
def test_calculate_victory_reward_draft_values(enemy_type, expected_reward):
    assert pr.calculate_victory_reward(enemy_type) == expected_reward


@pytest.mark.parametrize("enemy_type,expected_reward", [("mouse", 1), ("wolf", 5), ("boar", 15)])
def test_calculate_battle_reward_victory_matches_victory_reward(enemy_type, expected_reward):
    assert pr.calculate_battle_reward("victory", enemy_type) == expected_reward


@pytest.mark.parametrize("outcome", ["defeat", "player_fled", "enemy_fled"])
@pytest.mark.parametrize("enemy_type", ["mouse", "wolf", "boar"])
def test_calculate_battle_reward_no_reward_for_non_victory_outcomes(outcome, enemy_type):
    # §7: "Наказания за поражение или побег нет" — но и награды тоже нет.
    assert pr.calculate_battle_reward(outcome, enemy_type) == 0
