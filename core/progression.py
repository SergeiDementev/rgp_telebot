"""Формулы прогрессии по docs/gameplay_loop_mvp.md.

Только чистые функции: вход -> выход, без побочных эффектов и без хранения
состояния между вызовами.
"""

from datetime import datetime
from typing import Optional

HP_MAX_BASE = 20
HP_MAX_PER_VITALITY = 10

REGEN_PER_SECOND_DEFAULT = 1

LEVEL_THRESHOLD_STEP_DEFAULT = 10

VICTORY_REWARD_DEFAULTS = {"mouse": 1, "wolf": 5, "boar": 15}

STAT_NAMES = {"strength", "agility", "luck", "vitality"}


class NoStatPointsAvailableError(Exception):
    """Нет доступных очков прокачки для распределения (§5)."""


def calculate_hp_max(vitality: float) -> float:
    """§3: HP_max = 20 + Здоровье × 10."""
    return HP_MAX_BASE + vitality * HP_MAX_PER_VITALITY


def get_current_hp(
    hp_current: float,
    hp_max: float,
    last_update_at: datetime,
    now: datetime,
    regen_per_second: float = REGEN_PER_SECOND_DEFAULT,
) -> float:
    """§8: ленивый пересчёт HP по прошедшему времени, без фонового процесса."""
    elapsed_seconds = max((now - last_update_at).total_seconds(), 0)
    regenerated = elapsed_seconds * regen_per_second
    return min(hp_current + regenerated, hp_max)


def time_to_full_hp(
    hp_current: float,
    hp_max: float,
    regen_per_second: float = REGEN_PER_SECOND_DEFAULT,
) -> float:
    """§8: сколько секунд осталось до полного восстановления HP."""
    missing = hp_max - hp_current
    if missing <= 0:
        return 0
    return missing / regen_per_second


def calculate_level_threshold(level: int, step: int = LEVEL_THRESHOLD_STEP_DEFAULT) -> int:
    """§5: threshold(N) = 10×(N-1)×N/2 (threshold(1) = 0)."""
    if level < 1:
        raise ValueError("level must be >= 1")
    return step * (level - 1) * level // 2


def calculate_level_for_points(victory_points: int, step: int = LEVEL_THRESHOLD_STEP_DEFAULT) -> int:
    """§5: текущий уровень — наибольший N, чей порог не превышает victory_points."""
    level = 1
    while calculate_level_threshold(level + 1, step) <= victory_points:
        level += 1
    return level


def points_to_next_level(victory_points: int, step: int = LEVEL_THRESHOLD_STEP_DEFAULT) -> int:
    """§4/§5: сколько победных очков осталось до следующего уровня."""
    current_level = calculate_level_for_points(victory_points, step)
    next_threshold = calculate_level_threshold(current_level + 1, step)
    return next_threshold - victory_points


def calculate_levels_gained(
    old_points: int, new_points: int, step: int = LEVEL_THRESHOLD_STEP_DEFAULT
) -> int:
    """§5: сколько уровней (= очков прокачки) начислить за прирост очков."""
    return calculate_level_for_points(new_points, step) - calculate_level_for_points(old_points, step)


def calculate_victory_reward(enemy_type: str, rewards: Optional[dict] = None) -> int:
    """§7: награда победными очками по типу моба (черновые значения)."""
    rewards = rewards if rewards is not None else VICTORY_REWARD_DEFAULTS
    return rewards[enemy_type]


def calculate_battle_reward(outcome: str, enemy_type: str, rewards: Optional[dict] = None) -> int:
    """§7: награда только при victory — defeat/player_fled/enemy_fled её не дают."""
    if outcome != "victory":
        return 0
    return calculate_victory_reward(enemy_type, rewards)


def allocate_stat_point(unspent_stat_points: int, current_stat_value: int, stat: str) -> tuple[int, int]:
    """§2/§5: списать 1 очко прокачки, увеличить выбранный стат на 1.

    Возвращает (новое unspent_stat_points, новое значение стата). Одна и та же
    функция используется и при распределении стартового пула на создании
    персонажа, и при обычном левел-апе — механика идентична (§5). Отмены или
    перераспределения уже потраченных очков нет — списание необратимо.
    """
    if stat not in STAT_NAMES:
        raise ValueError(f"unknown stat: {stat!r}")
    if unspent_stat_points <= 0:
        raise NoStatPointsAvailableError("no unspent stat points available")
    return unspent_stat_points - 1, current_stat_value + 1
