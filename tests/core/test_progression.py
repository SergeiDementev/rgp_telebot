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
        (2, 8),
        (3, 20),
        (4, 36),
        (5, 56),
    ],
)
def test_calculate_level_threshold_matches_doc_example(level, expected_threshold):
    assert pr.calculate_level_threshold(level) == expected_threshold


@pytest.mark.parametrize(
    "victory_points,expected_level",
    [
        (7, 1),    # на 1 очко меньше порога уровня 2 — уровень ещё не сменился
        (8, 2),    # ровно на пороге — уровень уже сменился
        (19, 2),   # на 1 очко меньше порога уровня 3
        (20, 3),   # ровно на пороге уровня 3
    ],
)
def test_calculate_level_for_points_boundary_is_inclusive(victory_points, expected_level):
    assert pr.calculate_level_for_points(victory_points) == expected_level


def test_calculate_levels_gained_can_skip_several_levels_at_once():
    # Крупная награда может сразу перепрыгнуть через несколько порогов подряд:
    # с уровня 1 (порог 8 ещё не достигнут) сразу до уровня 4 (порог 36).
    assert pr.calculate_levels_gained(old_points=6, new_points=37) == 3
    assert pr.calculate_level_for_points(6) == 1
    assert pr.calculate_level_for_points(37) == 4


@pytest.mark.parametrize(
    "old_points,new_points,expected_gained",
    [
        (5, 7, 0),   # прирост, не достигающий порога
        (7, 8, 1),   # прирост ровно до порога — засчитывается
        (8, 8, 0),   # без прироста — новых уровней нет
    ],
)
def test_calculate_levels_gained_boundaries(old_points, new_points, expected_gained):
    assert pr.calculate_levels_gained(old_points, new_points) == expected_gained


def test_points_to_next_level_basic():
    # 25 очков — это уровень 3 (порог 20), до уровня 4 (порог 36) остаётся 11.
    assert pr.calculate_level_for_points(25) == 3
    assert pr.points_to_next_level(25) == 11


def test_calculate_stat_points_gained_identity_at_rate_one():
    # При множителе 1 функция ведёт себя как identity — регрессия к
    # поведению до появления STAT_POINTS_PER_LEVEL (levels_gained напрямую
    # использовался как число очков прокачки).
    for levels_gained in (0, 1, 3, 7):
        assert pr.calculate_stat_points_gained(levels_gained, stat_points_per_level=1) == levels_gained


def test_calculate_stat_points_gained_scales_with_custom_rate():
    # 3 пройденных уровня при stat_points_per_level=3 -> 9 очков, не 3.
    assert pr.calculate_stat_points_gained(3, stat_points_per_level=3) == 9


def test_stat_points_per_level_default_is_calibrated_value():
    # Итог калибровки (этап 2, backend_plan.md §8): 2 очка прокачки за уровень.
    assert pr.STAT_POINTS_PER_LEVEL == 2
    assert pr.calculate_stat_points_gained(3) == 6  # использует дефолт


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


# ---------------------------------------------------------------------------
# 5. Распределение очков прокачки — allocate_stat_point
# ---------------------------------------------------------------------------


def test_allocate_stat_point_decrements_points_and_increments_stat():
    new_points, new_value = pr.allocate_stat_point(
        unspent_stat_points=5, current_stat_value=3, stat="strength"
    )
    assert new_points == 4
    assert new_value == 4


@pytest.mark.parametrize("stat", sorted(pr.STAT_NAMES))
def test_allocate_stat_point_works_for_every_known_stat(stat):
    new_points, new_value = pr.allocate_stat_point(
        unspent_stat_points=1, current_stat_value=0, stat=stat
    )
    assert (new_points, new_value) == (0, 1)


def test_allocate_stat_point_raises_when_no_points_available():
    with pytest.raises(pr.NoStatPointsAvailableError):
        pr.allocate_stat_point(unspent_stat_points=0, current_stat_value=3, stat="strength")


def test_allocate_stat_point_rejects_unknown_stat_name():
    with pytest.raises(ValueError):
        pr.allocate_stat_point(unspent_stat_points=5, current_stat_value=3, stat="intelligence")


def test_allocate_stat_point_has_no_undo_mechanism():
    # Нет отдельной функции отмены — списание необратимо (§5). Единственный
    # способ "вернуть" очко — не вызывать allocate_stat_point вообще; после
    # вызова прежнее состояние нигде не сохраняется и не восстанавливается.
    points, value = 3, 10
    points, value = pr.allocate_stat_point(points, value, "agility")
    points, value = pr.allocate_stat_point(points, value, "agility")
    assert (points, value) == (1, 12)
    assert not hasattr(pr, "undo_stat_point")
    assert not hasattr(pr, "deallocate_stat_point")


def test_allocate_stat_point_carries_over_unspent_points_from_creation_to_level_up():
    # §2/§5: при создании персонажа необязательно тратить весь стартовый пул —
    # остаток просто переносится в unspent_stat_points и используется той же
    # функцией на обычном левел-апе, без отдельного шага "переноса".
    creation_pool = 5
    strength = 3

    # Игрок тратит только 3 из 5 очков при создании персонажа.
    creation_pool, strength = pr.allocate_stat_point(creation_pool, strength, "strength")
    creation_pool, strength = pr.allocate_stat_point(creation_pool, strength, "strength")
    creation_pool, strength = pr.allocate_stat_point(creation_pool, strength, "strength")
    assert creation_pool == 2  # оставшиеся 2 очка никуда не делись

    # Персонаж выходит в бой, получает уровень (+1 очко) — вызывающий код
    # просто прибавляет его к тому же unspent_stat_points, не обнуляя остаток.
    unspent_after_level_up = creation_pool + 1
    assert unspent_after_level_up == 3

    # Тот же allocate_stat_point тратит очки из объединённого пула на левел-апе.
    unspent_after_level_up, strength = pr.allocate_stat_point(
        unspent_after_level_up, strength, "strength"
    )
    assert unspent_after_level_up == 2
    assert strength == 7  # старт 3 + 3 (создание) + 1 (левел-ап) = 4 потраченных очка
