"""Формулы боевого ядра по docs/combat_mechanics.md.

Только чистые функции: вход -> выход, без побочных эффектов и без хранения
состояния между вызовами. Кубики не бросаются внутри модуля — все результаты
бросков (d10 и т.д.) передаются аргументами, функции лишь трактуют их по
формулам из документа. Полный цикл боя (§9), выбор побега и определение
итогового исхода — ответственность вызывающего кода (сессии боя), не этого
модуля.
"""

import math
from typing import NamedTuple, Optional

DICE_SIDES = 10

# --- §3 Кубик атаки (Сила) ---
ATTACK_MISS_MAX_FACE = 2
ATTACK_FIXED_MAX_FACE = 5
ATTACK_FIXED_PERCENT = 50
ATTACK_SCALING_MIN_FACE = 6
ATTACK_SCALING_MIN_PERCENT = 60
ATTACK_SCALING_STEP_PERCENT = 10

# --- §3a Мощный удар (альтернатива атаке, только игрок) ---
POWER_ATTACK_MISS_MAX_FACE = 4
POWER_ATTACK_DAMAGE_MULTIPLIER = 1.3

# --- Черновые значения для калибровки (§11), используются как дефолты ---
DODGE_MIN_FACES_DEFAULT = 1
FLEE_MIN_FACES_DEFAULT = 1
FLEE_THRESHOLD_PERCENT_DEFAULT = 25
CIRCUMSTANCE_MODIFIER_PERCENT_DEFAULT = 20


def resolve_attack_percent(attack_roll: int) -> Optional[int]:
    """§3: процент от Силы по грани атаки, либо None при промахе (1-2)."""
    if attack_roll <= ATTACK_MISS_MAX_FACE:
        return None
    if attack_roll <= ATTACK_FIXED_MAX_FACE:
        return ATTACK_FIXED_PERCENT
    step = attack_roll - ATTACK_SCALING_MIN_FACE
    return ATTACK_SCALING_MIN_PERCENT + step * ATTACK_SCALING_STEP_PERCENT


def resolve_power_attack_percent(attack_roll: int) -> Optional[int]:
    """§3a: процент от Силы по грани мощного удара, либо None при промахе (1-4)."""
    if attack_roll <= POWER_ATTACK_MISS_MAX_FACE:
        return None
    if attack_roll <= ATTACK_FIXED_MAX_FACE:
        return ATTACK_FIXED_PERCENT
    step = attack_roll - ATTACK_SCALING_MIN_FACE
    return ATTACK_SCALING_MIN_PERCENT + step * ATTACK_SCALING_STEP_PERCENT


def calculate_damage(strength: float, attack_percent: int) -> int:
    """§3: Урон = Сила × процент / 100, округлён до целого.

    HP — дробные величины создавали путаницу без какой-либо пользы (живой
    противник с 0.2 HP выглядел мёртвым в отображении, см. docs/notes.md) —
    округляем сразу здесь, а не только при рендере: тогда внутреннее
    состояние всегда совпадает с тем, что показано на экране."""
    return round(strength * attack_percent / 100)


def calculate_saturating_success_faces(
    stat: float, max_faces: int, k: float, min_faces: int = 1
) -> int:
    """Кривая насыщения общая для §4 (уворот) и §6 (побег):
    MIN_FACES + round((MAX_FACES − MIN_FACES) × stat / (stat + K)).
    """
    if stat + k <= 0:
        return min_faces
    return min_faces + round((max_faces - min_faces) * stat / (stat + k))


def calculate_dodge_success_faces(
    agility: float, max_faces: int, k: float, min_faces: int = DODGE_MIN_FACES_DEFAULT
) -> int:
    """§4: количество граней d10, дающих полный уворот."""
    return calculate_saturating_success_faces(agility, max_faces, k, min_faces)


def is_dodge_successful(dodge_roll: int, success_faces: int) -> bool:
    """§4: полный уворот, если бросок попал в одну из успешных граней."""
    return dodge_roll <= success_faces


def calculate_double_strike_success_faces(
    luck: float, k: float, dice_sides: int = DICE_SIDES
) -> int:
    """§5: floor(dice_sides × Удача / (Удача + K)), асимптота к dice_sides."""
    if luck + k <= 0:
        return 0
    return math.floor(dice_sides * luck / (luck + k))


def is_double_strike_triggered(luck_roll: int, success_faces: int) -> bool:
    """§5: двойной удар, если бросок Удачи попал в успешную грань."""
    return luck_roll <= success_faces


def is_hp_at_or_below_flee_threshold(
    current_hp: float,
    max_hp: float,
    threshold_percent: float = FLEE_THRESHOLD_PERCENT_DEFAULT,
) -> bool:
    """§6: HP текущей стороны ≤ порога, открывающего попытку проверки побега."""
    return current_hp <= max_hp * threshold_percent / 100


def calculate_flee_opportunity_success_faces(
    luck: float, max_faces: int, k: float, min_faces: int = FLEE_MIN_FACES_DEFAULT
) -> int:
    """§6: та же кривая насыщения, что и уворот, но с собственными MIN/MAX/K."""
    return calculate_saturating_success_faces(luck, max_faces, k, min_faces)


def is_flee_opportunity_triggered(luck_roll: int, success_faces: int) -> bool:
    """§6: успешный бросок открывает выбор "сбежать/продолжать", не сам побег."""
    return luck_roll <= success_faces


class FleeAttemptResult(NamedTuple):
    missed: bool
    attack_percent: Optional[int]
    damage: float
    fleeing_hp_after: float
    fleeing_defeated: bool


def resolve_flee_attempt(
    pursuer_strength: float, attack_roll: int, fleeing_current_hp: float
) -> FleeAttemptResult:
    """§7: безответный удар преследователя без защиты убегающего."""
    attack_percent = resolve_attack_percent(attack_roll)
    damage = 0.0 if attack_percent is None else calculate_damage(pursuer_strength, attack_percent)
    fleeing_hp_after = max(fleeing_current_hp - damage, 0.0)
    return FleeAttemptResult(
        missed=attack_percent is None,
        attack_percent=attack_percent,
        damage=damage,
        fleeing_hp_after=fleeing_hp_after,
        fleeing_defeated=fleeing_hp_after <= 0,
    )


def resolve_circumstance_outcome(roll: int) -> Optional[str]:
    """§8: 1-3 -> "debuff", 4-7 -> None (нет обстоятельства), 8-10 -> "buff"."""
    if roll <= 3:
        return "debuff"
    if roll <= 7:
        return None
    return "buff"


def apply_circumstance_strength_modifier(
    strength: float,
    outcome: Optional[str],
    modifier_percent: float = CIRCUMSTANCE_MODIFIER_PERCENT_DEFAULT,
) -> float:
    """§8: модификатор относителен к кидающему (buff усиливает его, debuff ослабляет)."""
    if outcome == "buff":
        return strength * (1 + modifier_percent / 100)
    if outcome == "debuff":
        return strength * (1 - modifier_percent / 100)
    return strength


class StrikeResult(NamedTuple):
    missed: bool
    attack_percent: Optional[int]
    dodge_success_faces: Optional[int]
    dodged: Optional[bool]
    damage: float


def resolve_strike(
    attacker_strength: float,
    defender_agility: float,
    attack_roll: int,
    dodge_roll: int,
    dodge_max_faces: int,
    dodge_k: float,
    dodge_min_faces: int = DODGE_MIN_FACES_DEFAULT,
    power_attack: bool = False,
) -> StrikeResult:
    """§3(+§3a)+§4: один удар целиком — атака (обычная либо мощная), при
    попадании уворот, итоговый урон. Уворот не различает тип атаки —
    работает одинаково для мобов, волка/кабана и босса, как и всегда."""
    attack_percent = (
        resolve_power_attack_percent(attack_roll) if power_attack else resolve_attack_percent(attack_roll)
    )
    if attack_percent is None:
        return StrikeResult(
            missed=True,
            attack_percent=None,
            dodge_success_faces=None,
            dodged=None,
            damage=0.0,
        )

    dodge_success_faces = calculate_dodge_success_faces(
        defender_agility, dodge_max_faces, dodge_k, dodge_min_faces
    )
    dodged = is_dodge_successful(dodge_roll, dodge_success_faces)
    if dodged:
        damage = 0.0
    elif power_attack:
        # §3a: множитель применяется ДО округления, не к уже округлённому
        # calculate_damage() — иначе округление накапливало бы погрешность.
        damage = round(attacker_strength * attack_percent / 100 * POWER_ATTACK_DAMAGE_MULTIPLIER)
    else:
        damage = calculate_damage(attacker_strength, attack_percent)
    return StrikeResult(
        missed=False,
        attack_percent=attack_percent,
        dodge_success_faces=dodge_success_faces,
        dodged=dodged,
        damage=damage,
    )


def resolve_initiative(first_roll: int, second_roll: int) -> Optional[str]:
    """§9 шаг 1: "first" | "second" — кто ходит первым, либо None при ничьей
    (документ не определяет тай-брейк — ничья считается поводом перебросить).
    """
    if first_roll > second_roll:
        return "first"
    if second_roll > first_roll:
        return "second"
    return None
