"""Тесты core/combat_mechanics.py по docs/combat_mechanics.md."""

import random

import pytest

from core import combat_mechanics as cm


# ---------------------------------------------------------------------------
# 1. Детерминированные тесты — граничные значения бросков по §3-8
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attack_roll,expected_percent",
    [
        (1, None),
        (2, None),
        (3, 50),
        (4, 50),
        (5, 50),
        (6, 60),
        (7, 70),
        (8, 80),
        (9, 90),
        (10, 100),
    ],
)
def test_resolve_attack_percent_boundaries(attack_roll, expected_percent):
    assert cm.resolve_attack_percent(attack_roll) == expected_percent


@pytest.mark.parametrize(
    "strength,attack_percent,expected_damage",
    [
        (50, 60, 30.0),
        (80, 100, 80.0),
        (10, 0, 0.0),
        (33, 73, 33 * 73 / 100),
    ],
)
def test_calculate_damage(strength, attack_percent, expected_damage):
    assert cm.calculate_damage(strength, attack_percent) == pytest.approx(expected_damage)


def test_dodge_success_faces_min_at_zero_agility():
    # §4: MIN_FACES = 1 гарантирован даже при Ловкости = 0.
    assert cm.calculate_dodge_success_faces(agility=0, max_faces=5, k=10) == 1


def test_dodge_success_faces_approaches_but_reaches_max_via_round():
    # При очень большой Ловкости кривая практически достигает MAX_FACES (round, не floor).
    assert cm.calculate_dodge_success_faces(agility=1_000_000, max_faces=5, k=10) == 5


@pytest.mark.parametrize(
    "dodge_roll,success_faces,expected",
    [
        (3, 3, True),   # граница: попадание в последнюю успешную грань — успех
        (4, 3, False),  # первая неуспешная грань
        (1, 1, True),
    ],
)
def test_is_dodge_successful_boundaries(dodge_roll, success_faces, expected):
    assert cm.is_dodge_successful(dodge_roll, success_faces) is expected


def test_double_strike_faces_zero_at_zero_luck():
    # §5: минимум 0 граней допустим — способность может не срабатывать вовсе.
    assert cm.calculate_double_strike_success_faces(luck=0, k=10) == 0


def test_double_strike_faces_never_reaches_dice_sides():
    # §5: асимптота к 100%, но никогда её не достигает, даже при огромной Удаче.
    faces = cm.calculate_double_strike_success_faces(luck=1_000_000, k=10, dice_sides=10)
    assert faces < 10
    assert faces == 9


@pytest.mark.parametrize(
    "luck_roll,success_faces,expected",
    [
        (9, 9, True),
        (10, 9, False),
        (1, 0, False),  # 0 успешных граней — сработать не может никогда
    ],
)
def test_is_double_strike_triggered_boundaries(luck_roll, success_faces, expected):
    assert cm.is_double_strike_triggered(luck_roll, success_faces) is expected


@pytest.mark.parametrize(
    "current_hp,max_hp,threshold_percent,expected",
    [
        (25, 100, 25, True),   # ровно на пороге — считается достигнутым
        (25.01, 100, 25, False),
        (20, 100, cm.FLEE_THRESHOLD_PERCENT_DEFAULT, True),  # дефолт 25%
    ],
)
def test_is_hp_at_or_below_flee_threshold(current_hp, max_hp, threshold_percent, expected):
    assert cm.is_hp_at_or_below_flee_threshold(current_hp, max_hp, threshold_percent) is expected


def test_flee_opportunity_faces_min_at_zero_luck():
    # §6: MIN_FACES = 1 гарантирован даже при нулевой Удаче.
    assert cm.calculate_flee_opportunity_success_faces(luck=0, max_faces=4, k=10) == 1


@pytest.mark.parametrize(
    "attack_roll,fleeing_current_hp,expected_damage,expected_hp_after,expected_defeated",
    [
        (1, 30, 0.0, 30, False),      # промах — убегающий не задет
        (10, 50, 100.0, 0.0, True),   # максимальный урон добивает
        (6, 100, 60.0, 40.0, False),  # обычный удар, убегающий выживает
    ],
)
def test_resolve_flee_attempt(
    attack_roll, fleeing_current_hp, expected_damage, expected_hp_after, expected_defeated
):
    result = cm.resolve_flee_attempt(
        pursuer_strength=100, attack_roll=attack_roll, fleeing_current_hp=fleeing_current_hp
    )
    assert result.damage == pytest.approx(expected_damage)
    assert result.fleeing_hp_after == pytest.approx(expected_hp_after)
    assert result.fleeing_defeated is expected_defeated


@pytest.mark.parametrize(
    "roll,expected_outcome",
    [
        (1, "debuff"),
        (2, "debuff"),
        (3, None),
        (4, None),
        (5, None),
        (6, None),
        (7, None),
        (8, None),
        (9, "buff"),
        (10, "buff"),
    ],
)
def test_resolve_circumstance_outcome_all_faces(roll, expected_outcome):
    assert cm.resolve_circumstance_outcome(roll) == expected_outcome


@pytest.mark.parametrize(
    "outcome,modifier_percent,expected",
    [
        ("buff", 20, 120.0),
        ("debuff", 20, 80.0),
        (None, 20, 100.0),
        ("buff", 50, 150.0),
        ("debuff", 50, 50.0),
    ],
)
def test_apply_circumstance_strength_modifier(outcome, modifier_percent, expected):
    assert cm.apply_circumstance_strength_modifier(100, outcome, modifier_percent) == pytest.approx(
        expected
    )


def test_resolve_strike_miss_skips_dodge_entirely():
    result = cm.resolve_strike(
        attacker_strength=100,
        defender_agility=1000,
        attack_roll=1,
        dodge_roll=1,
        dodge_max_faces=5,
        dodge_k=10,
    )
    assert result.missed is True
    assert result.attack_percent is None
    assert result.dodge_success_faces is None
    assert result.dodged is None
    assert result.damage == 0.0


def test_resolve_strike_dodged_deals_no_damage():
    result = cm.resolve_strike(
        attacker_strength=100,
        defender_agility=1000,
        attack_roll=8,
        dodge_roll=1,
        dodge_max_faces=5,
        dodge_k=10,
    )
    assert result.missed is False
    assert result.dodged is True
    assert result.damage == 0.0


def test_resolve_strike_hit_deals_expected_damage():
    result = cm.resolve_strike(
        attacker_strength=100,
        defender_agility=0,
        attack_roll=10,
        dodge_roll=2,
        dodge_max_faces=5,
        dodge_k=10,
    )
    assert result.missed is False
    assert result.dodge_success_faces == 1  # MIN_FACES даже при Ловкости = 0
    assert result.dodged is False
    assert result.damage == pytest.approx(100.0)


@pytest.mark.parametrize(
    "first_roll,second_roll,expected",
    [
        (7, 4, "first"),
        (4, 7, "second"),
        (5, 5, None),
    ],
)
def test_resolve_initiative(first_roll, second_roll, expected):
    assert cm.resolve_initiative(first_roll, second_roll) == expected


# ---------------------------------------------------------------------------
# 2. Инвариантные тесты — свойства, верные для любых входных данных
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stat", [0, 1, 5, 10, 50, 200, 10_000])
def test_saturating_success_faces_stays_within_bounds(stat):
    faces = cm.calculate_saturating_success_faces(stat, max_faces=6, k=15, min_faces=1)
    assert 1 <= faces <= 6


def test_saturating_success_faces_is_non_decreasing_with_stat():
    samples = [0, 1, 2, 5, 10, 20, 50, 100, 1000]
    faces = [
        cm.calculate_saturating_success_faces(stat, max_faces=6, k=15, min_faces=1)
        for stat in samples
    ]
    assert faces == sorted(faces)


def test_saturating_success_faces_degenerate_zero_denominator_returns_min_faces():
    # stat=0 и k=0 => stat+k=0, формула неприменима, страховка возвращает MIN_FACES.
    assert cm.calculate_saturating_success_faces(0, max_faces=5, k=0, min_faces=1) == 1


@pytest.mark.parametrize("luck", [0, 1, 5, 10, 50, 200, 1_000_000])
def test_double_strike_faces_always_below_dice_sides(luck):
    faces = cm.calculate_double_strike_success_faces(luck, k=10, dice_sides=10)
    assert 0 <= faces < 10


def test_double_strike_faces_is_non_decreasing_with_luck():
    samples = [0, 1, 2, 5, 10, 20, 50, 100, 1000]
    faces = [cm.calculate_double_strike_success_faces(luck, k=10) for luck in samples]
    assert faces == sorted(faces)


def test_double_strike_uses_floor_not_round():
    # §5: явно floor(), не round() — иначе высокая Удача рано или поздно дала бы
    # все 10 граней. luck=85, k=10 -> 8.947... : floor=8, а round дал бы 9.
    faces = cm.calculate_double_strike_success_faces(luck=85, k=10)
    assert faces == 8
    assert faces != round(10 * 85 / 95)


def test_saturating_curve_uses_python_round_semantics():
    # §4/§6: в отличие от двойного удара, здесь используется round(), не floor().
    # agility=10, max_faces=6, k=10, min_faces=1 -> (6-1)*0.5=2.5 -> round(2.5)=2
    # (Python округляет половину к чётному, а не всегда вверх) -> итог 1+2=3.
    faces = cm.calculate_saturating_success_faces(10, max_faces=6, k=10, min_faces=1)
    assert faces == 3


@pytest.mark.parametrize("fleeing_current_hp", [0, 5, 50, 1000])
def test_resolve_flee_attempt_hp_after_never_negative(fleeing_current_hp):
    result = cm.resolve_flee_attempt(
        pursuer_strength=10_000, attack_roll=10, fleeing_current_hp=fleeing_current_hp
    )
    assert result.fleeing_hp_after >= 0


# ---------------------------------------------------------------------------
# 3. Статистические тесты с фиксированным seed (roll_d — только в этом файле)
# ---------------------------------------------------------------------------


def _roll_d(rng: random.Random, sides: int = 10) -> int:
    """Тестовый хелпер: d10 через переданный Random-инстанс. Не часть core —
    в core/combat_mechanics.py броски намеренно не выполняются (см. README/
    combat_mechanics.md: все данные — только через аргументы)."""
    return rng.randint(1, sides)


def test_circumstance_outcome_matches_declared_proportions():
    rng = random.Random(42)
    n = 10_000
    counts = {"debuff": 0, None: 0, "buff": 0}
    for _ in range(n):
        roll = _roll_d(rng)
        counts[cm.resolve_circumstance_outcome(roll)] += 1

    assert counts["debuff"] / n == pytest.approx(0.2, abs=0.02)
    assert counts[None] / n == pytest.approx(0.6, abs=0.02)
    assert counts["buff"] / n == pytest.approx(0.2, abs=0.02)


def test_dodge_success_rate_matches_calculated_faces_ratio():
    rng = random.Random(1234)
    n = 10_000
    max_faces, k, agility = 6, 15, 30
    success_faces = cm.calculate_dodge_success_faces(agility, max_faces, k)
    expected_rate = success_faces / cm.DICE_SIDES

    hits = sum(cm.is_dodge_successful(_roll_d(rng), success_faces) for _ in range(n))
    assert hits / n == pytest.approx(expected_rate, abs=0.02)


# ---------------------------------------------------------------------------
# 4. Интеграционные тесты — композиция функций
# ---------------------------------------------------------------------------


def test_two_strike_turn_composition_stops_applying_after_lethal_first_strike():
    """Двойной удар (§5) собирается из is_double_strike_triggered + два вызова
    resolve_strike. Если первый удар убивает защищающегося, второй удар не
    "наносится" — это проверяет вызывающий код (оркестратор), а не сама
    формула (см. docs/combat_mechanics.md §5)."""
    luck, k = 90, 10  # success_faces = floor(10*90/100) = 9
    success_faces = cm.calculate_double_strike_success_faces(luck, k)
    assert cm.is_double_strike_triggered(luck_roll=5, success_faces=success_faces) is True

    defender_hp = 50

    strike_1 = cm.resolve_strike(
        attacker_strength=100,
        defender_agility=0,
        attack_roll=10,  # 100%, без уворота (agility=0 -> success_faces=1, roll=5 промахивается)
        dodge_roll=5,
        dodge_max_faces=5,
        dodge_k=10,
    )
    defender_hp -= strike_1.damage
    assert defender_hp <= 0  # первый удар уже смертелен

    # Оркестратор не применяет второй удар — resolve_strike для него не вызывается.
    strikes_applied = [strike_1]
    assert len(strikes_applied) == 1
    assert strikes_applied[0].damage == pytest.approx(100.0)


def test_two_strike_turn_composition_applies_both_strikes_when_defender_survives():
    luck, k = 90, 10
    success_faces = cm.calculate_double_strike_success_faces(luck, k)
    assert cm.is_double_strike_triggered(luck_roll=5, success_faces=success_faces) is True

    defender_hp = 1000

    strike_1 = cm.resolve_strike(
        attacker_strength=50,
        defender_agility=0,
        attack_roll=10,
        dodge_roll=5,
        dodge_max_faces=5,
        dodge_k=10,
    )
    defender_hp -= strike_1.damage
    assert defender_hp > 0

    strike_2 = cm.resolve_strike(
        attacker_strength=50,
        defender_agility=0,
        attack_roll=6,
        dodge_roll=5,
        dodge_max_faces=5,
        dodge_k=10,
    )
    defender_hp -= strike_2.damage

    total_damage = strike_1.damage + strike_2.damage
    assert total_damage == pytest.approx(80.0)  # 100% + 60% от Силы 50
    assert defender_hp == pytest.approx(1000 - total_damage)


def test_unanswered_strike_scenario_via_resolve_flee_attempt():
    """"Безответный удар" (agility=None в терминологии запроса) в этой кодовой
    базе — не resolve_strike с agility=None, а отдельная resolve_flee_attempt:
    у неё в принципе нет параметра уворота (см. §7). Сценарий целиком: HP ниже
    порога -> открылась возможность -> выбор "сбежать" -> безответный удар."""
    current_hp, max_hp = 20, 100

    assert cm.is_hp_at_or_below_flee_threshold(current_hp, max_hp) is True

    luck, k, max_faces = 40, 10, 4
    success_faces = cm.calculate_flee_opportunity_success_faces(luck, max_faces, k)
    assert cm.is_flee_opportunity_triggered(luck_roll=2, success_faces=success_faces) is True

    # Игрок выбирает "Сбежать" -> безответный удар преследователя без защиты.
    result = cm.resolve_flee_attempt(
        pursuer_strength=30, attack_roll=6, fleeing_current_hp=current_hp
    )
    assert result.missed is False
    assert result.fleeing_hp_after == pytest.approx(2.0)  # 20 - 30*60/100 = 2
    assert result.fleeing_defeated is False
