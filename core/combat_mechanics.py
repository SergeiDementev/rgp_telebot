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
POWER_ATTACK_DAMAGE_MULTIPLIER = 1.5

# --- Черновые значения для калибровки (§11), используются как дефолты ---
DODGE_MIN_FACES_DEFAULT = 1
FLEE_MIN_FACES_DEFAULT = 1
FLEE_THRESHOLD_PERCENT_DEFAULT = 25
CIRCUMSTANCE_MODIFIER_PERCENT_DEFAULT = 20


def resolve_attack_percent(attack_roll: int, *, power: bool = False) -> Optional[int]:
    """§3(+§3a): процент от Силы по грани атаки, либо None при промахе.

    Обычная атака и Мощный удар (только игрок) делят одну и ту же шкалу
    фиксированного/линейно растущего процента (3-5 -> 50%, 6-10 -> 60-100%)
    — отличается только порог промаха (1-2 грани обычная атака, 1-4 —
    мощный удар, §3a)."""
    miss_max_face = POWER_ATTACK_MISS_MAX_FACE if power else ATTACK_MISS_MAX_FACE
    if attack_roll <= miss_max_face:
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
    """Кривая насыщения с жёстким потолком, используется §6 (побег):
    MIN_FACES + round((MAX_FACES − MIN_FACES) × stat / (stat + K)).

    Раньше обслуживала и §4 (уворот), но та с 2026-09-22 (docs/notes.md,
    п.60) перешла на отдельную асимптотическую формулу без потолка
    (см. calculate_dodge_success_faces) — эта функция теперь только для
    побега, где жёсткий потолок остаётся дизайн-решением."""
    if stat + k <= 0:
        return min_faces
    return min_faces + round((max_faces - min_faces) * stat / (stat + k))


def calculate_dodge_success_faces(
    agility: float, k: float, dice_sides: int = DICE_SIDES, min_faces: int = DODGE_MIN_FACES_DEFAULT
) -> int:
    """§4: количество граней d10, дающих полный уворот. Асимптотическая
    кривая без жёсткого потолка (2026-09-22, docs/notes.md, п.60) — тот же
    принцип, что у двойного удара (§5): floor(), не round(), чтобы 100% не
    достигалось ни при каком конечном значении Ловкости, плюс сдвиг
    +min_faces для гарантированного ненулевого минимума при Ловкости=0."""
    if agility + k <= 0:
        return min_faces
    return min_faces + math.floor((dice_sides - min_faces) * agility / (agility + k))


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


def resolve_circumstance_multiplier(
    outcome: Optional[str],
    modifier_percent: float = CIRCUMSTANCE_MODIFIER_PERCENT_DEFAULT,
) -> float:
    """§8: голый множитель Силы кидающего по исходу обстоятельства (buff ->
    ×(1+modifier), debuff -> ×(1-modifier), иначе ×1) — без домножения на
    конкретное значение Силы, чтобы вызывающий код мог сохранить множитель
    отдельно и применить его позже (api/routers/encounter.py хранит его в
    CombatSession.strength_modifier_*, до самого момента удара)."""
    if outcome == "buff":
        return 1 + modifier_percent / 100
    if outcome == "debuff":
        return 1 - modifier_percent / 100
    return 1.0


def apply_circumstance_strength_modifier(
    strength: float,
    outcome: Optional[str],
    modifier_percent: float = CIRCUMSTANCE_MODIFIER_PERCENT_DEFAULT,
) -> float:
    """§8: модификатор относителен к кидающему (buff усиливает его, debuff ослабляет)."""
    return strength * resolve_circumstance_multiplier(outcome, modifier_percent)


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
    dodge_k: float,
    dodge_min_faces: int = DODGE_MIN_FACES_DEFAULT,
    power_attack: bool = False,
) -> StrikeResult:
    """§3(+§3a)+§4: один удар целиком — атака (обычная либо мощная), при
    попадании уворот, итоговый урон. Уворот не различает тип атаки —
    работает одинаково для мобов, волка/кабана и босса, как и всегда."""
    attack_percent = resolve_attack_percent(attack_roll, power=power_attack)
    if attack_percent is None:
        return StrikeResult(
            missed=True,
            attack_percent=None,
            dodge_success_faces=None,
            dodged=None,
            damage=0.0,
        )

    dodge_success_faces = calculate_dodge_success_faces(defender_agility, dodge_k, min_faces=dodge_min_faces)
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
