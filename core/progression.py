"""Формулы прогрессии по docs/gameplay_loop_mvp.md.

Только чистые функции: вход -> выход, без побочных эффектов и без хранения
состояния между вызовами.
"""

import math
from datetime import datetime
from typing import Optional

HP_MAX_BASE = 20
HP_MAX_PER_VITALITY = 10

REGEN_PER_SECOND_DEFAULT = 1

LEVEL_THRESHOLD_STEP_DEFAULT = 4

STAT_POINTS_PER_LEVEL = 2

VICTORY_REWARD_DEFAULTS = {"mouse": 1, "wolf": 5, "boar": 15}

# §6 gameplay_loop_mvp.md: пропорции поиска противника смещаются по уровню —
# от 60/30/10 (мышь/волк/кабан) на 1-2 уровне до зеркальных 10/30/60 на
# 9-10 уровне, дальше плато. Волк держится постоянно на 30%. Таблица по
# диапазонам, не формула — переход неравномерный (двойной шаг между 5-6 и
# 7-8 уровнем, намеренно, пересмотрено на плейтесте 2026-09-16), доверять
# линейной интерполяции здесь нельзя.
ENCOUNTER_FACES_BY_LEVEL_BAND = (
    # (верхняя граница диапазона, грани_мыши, грани_волка, грани_кабана) — сумма всегда 10
    (2, 6, 3, 1),
    (4, 5, 3, 2),
    (6, 4, 3, 3),
    (8, 2, 3, 5),
    (10, 1, 3, 6),
)

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
    """§8: ленивый пересчёт HP по прошедшему времени, без фонового процесса.

    Регенерация округляется вниз до целых HP — реальное время между
    запросами почти никогда не кратно секунде, без округления это была бы
    ещё одна дыра для дробных HP помимо урона в бою (см. docs/notes.md)."""
    elapsed_seconds = max((now - last_update_at).total_seconds(), 0)
    regenerated = math.floor(elapsed_seconds * regen_per_second)
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
    """§5: threshold(N) = threshold(N-1) + step×N = step×(N-1)×(N+2)/2 (threshold(1) = 0)."""
    if level < 1:
        raise ValueError("level must be >= 1")
    return step * (level - 1) * (level + 2) // 2


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
    """§5: сколько уровней пройдено за прирост победных очков."""
    return calculate_level_for_points(new_points, step) - calculate_level_for_points(old_points, step)


def calculate_stat_points_gained(
    levels_gained: int, stat_points_per_level: int = STAT_POINTS_PER_LEVEL
) -> int:
    """§5: очков прокачки за пройденные уровни = levels_gained × STAT_POINTS_PER_LEVEL."""
    return levels_gained * stat_points_per_level


def calculate_encounter_faces(level: int) -> tuple[int, int, int]:
    """§6: (грани_мыши, грани_волка, грани_кабана) для броска d10 на поиск
    противника — сумма всегда 10. Смотрит ENCOUNTER_FACES_BY_LEVEL_BAND по
    диапазону уровня; уровни выше последнего диапазона — плато на его
    значениях."""
    for max_level, mouse_faces, wolf_faces, boar_faces in ENCOUNTER_FACES_BY_LEVEL_BAND:
        if level <= max_level:
            return mouse_faces, wolf_faces, boar_faces
    _, mouse_faces, wolf_faces, boar_faces = ENCOUNTER_FACES_BY_LEVEL_BAND[-1]
    return mouse_faces, wolf_faces, boar_faces


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
