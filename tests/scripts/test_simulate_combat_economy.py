"""Тесты scripts/simulate_combat_economy.py — экономика (лут/золото/зелья)
поверх проверенного combat/progression движка (docs/notes.md)."""

import random

import pytest

from core import economy as ec
from scripts import simulate_combat_economy as sce


# ---------------------------------------------------------------------------
# Лут
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("enemy_name", ["mouse", "wolf", "boar"])
def test_roll_loot_always_returns_entry_from_the_table(enemy_name):
    rng = random.Random(42)
    valid_names = {entry[0] for entry in sce.LOOT_TABLE[enemy_name]}
    prices = {entry[0]: entry[2] for entry in sce.LOOT_TABLE[enemy_name]}
    for _ in range(50):
        name, price = sce.roll_loot(enemy_name, rng)
        assert name in valid_names
        assert price == prices[name]


def test_roll_loot_nothing_has_zero_price():
    for enemy_name in sce.LOOT_TABLE:
        entries = {name: price for name, _weight, price in sce.LOOT_TABLE[enemy_name]}
        assert entries["nothing"] == 0


# ---------------------------------------------------------------------------
# Выбор зелья для питья / покупки — чистые функции
# ---------------------------------------------------------------------------


def test_choose_potion_prefers_large_when_both_available():
    assert sce._choose_potion(potions_small=3, potions_large=1) == "large"


def test_choose_potion_falls_back_to_small():
    assert sce._choose_potion(potions_small=2, potions_large=0) == "small"


def test_choose_potion_returns_none_when_empty():
    assert sce._choose_potion(potions_small=0, potions_large=0) is None


def test_buy_potions_prefers_large_when_affordable():
    gold, small, large = sce.buy_potions(gold=100, potions_small=0, potions_large=0)
    assert (gold, small, large) == (100 - sce.LARGE_POTION_PRICE, 0, 1)


def test_buy_potions_falls_back_to_small_when_cannot_afford_large():
    gold, small, large = sce.buy_potions(
        gold=sce.SMALL_POTION_PRICE, potions_small=0, potions_large=0
    )
    assert (gold, small, large) == (0, 1, 0)


def test_buy_potions_respects_large_cap():
    gold, small, large = sce.buy_potions(
        gold=1000, potions_small=0, potions_large=sce.LARGE_POTION_CAP
    )
    # Большое упёрлось в потолок — переключается на Малое, а не игнорирует покупку.
    assert large == sce.LARGE_POTION_CAP
    assert small == 1
    assert gold == 1000 - sce.SMALL_POTION_PRICE


def test_buy_potions_does_nothing_when_both_capped():
    assert sce.buy_potions(1000, sce.SMALL_POTION_CAP, sce.LARGE_POTION_CAP) == (1000, sce.SMALL_POTION_CAP, sce.LARGE_POTION_CAP)


def test_buy_potions_does_nothing_when_too_poor():
    assert sce.buy_potions(gold=5, potions_small=0, potions_large=0) == (5, 0, 0)


# ---------------------------------------------------------------------------
# _maybe_drink_potion — мутирует fighter-словарь на месте
# ---------------------------------------------------------------------------


def _fighter(hp, hp_max, potions_small=0, potions_large=0):
    return {
        "hp": hp,
        "hp_max": hp_max,
        "potions_small": potions_small,
        "potions_large": potions_large,
        "potion_used": None,
        "potion_used_this_battle": False,
    }


def test_maybe_drink_potion_uses_large_when_hp_critical():
    attacker = _fighter(hp=10, hp_max=100, potions_small=1, potions_large=1)  # 10% — ниже порога 40%
    sce._maybe_drink_potion(attacker)
    assert attacker["potion_used"] == "large"
    assert attacker["potions_large"] == 0
    assert attacker["potions_small"] == 1  # малое не тронуто
    assert attacker["hp"] == 10 + 100 * sce.LARGE_POTION_HEAL_PERCENT / 100
    assert attacker["potion_used_this_battle"] is True


def test_maybe_drink_potion_falls_back_to_small_when_no_large():
    attacker = _fighter(hp=10, hp_max=100, potions_small=1, potions_large=0)
    sce._maybe_drink_potion(attacker)
    assert attacker["potion_used"] == "small"
    assert attacker["potions_small"] == 0


def test_maybe_drink_potion_does_nothing_above_threshold():
    attacker = _fighter(hp=50, hp_max=100, potions_small=1, potions_large=1)  # 50% — выше порога 40%
    sce._maybe_drink_potion(attacker)
    assert attacker["potion_used"] is None
    assert (attacker["potions_small"], attacker["potions_large"]) == (1, 1)


def test_maybe_drink_potion_does_nothing_without_potions():
    attacker = _fighter(hp=5, hp_max=100, potions_small=0, potions_large=0)
    sce._maybe_drink_potion(attacker)
    assert attacker["potion_used"] is None
    assert attacker["hp"] == 5


def test_maybe_drink_potion_respects_once_per_battle_limit():
    attacker = _fighter(hp=10, hp_max=100, potions_small=5, potions_large=5)
    sce._maybe_drink_potion(attacker)
    assert attacker["potions_large"] == 4
    # HP всё ещё низкое (только что вылечено, но следующий ход снова может
    # оказаться критическим) — второй раз пить нельзя, лимит "раз за бой".
    attacker["hp"] = 5
    sce._maybe_drink_potion(attacker)
    assert attacker["potions_large"] == 4  # не изменилось


def test_maybe_drink_potion_heals_by_percent_of_hp_max():
    attacker = _fighter(hp=39, hp_max=100, potions_small=0, potions_large=1)  # 39% -> лечит на 50% -> 89
    sce._maybe_drink_potion(attacker)
    assert attacker["hp"] == 89


def test_maybe_drink_potion_never_exceeds_hp_max(monkeypatch):
    # При текущих константах (порог 40%, лечение 25/50%) итог не может
    # математически превысить 90% hp_max — cap в реализации (`min()`) всё
    # равно на месте как защита на случай будущего пересмотра констант;
    # проверяем его, временно подняв процент лечения выше порога.
    # _maybe_drink_potion считает исцеление через core.economy.calculate_
    # heal_amount, а не через локальную константу sce.py — патчим её источник.
    monkeypatch.setattr(ec, "LARGE_POTION_HEAL_PERCENT", 90)
    attacker = _fighter(hp=39, hp_max=100, potions_small=0, potions_large=1)  # 39% ниже порога 40%
    sce._maybe_drink_potion(attacker)
    assert attacker["hp"] == 100  # 39 + 90 = 129 без cap'а, но не выше hp_max


# ---------------------------------------------------------------------------
# simulate_single_fight_economy — только игрок лечится, бот — никогда
# ---------------------------------------------------------------------------


def test_many_fights_run_without_error_even_when_enemy_hp_gets_critical():
    # Регрессия на "только игрок лечится" (docs/notes.md): в simulate_single_
    # fight_economy словарь `enemy` не содержит ключей potions_small/large
    # (_new_fighter их не создаёт) — если бы охрана `attacker_role == "player"`
    # перед _maybe_drink_potion сломалась, это упало бы KeyError'ом почти
    # сразу же, т.к. HP противника регулярно проседает ниже 40% в бою с
    # опасным мобом. Прогоняем много боёв против всех типов — если охрана
    # сломана, хотя бы один упадёт.
    from scripts import simulate_combat as sc

    player_stats = {"hp_max": 50, "strength": 5, "agility": 5, "luck": 2}
    rng = random.Random(3)
    for enemy_name, enemy_stats in sc.ENEMY_PRESETS.items():
        for _ in range(200):
            result = sce.simulate_single_fight_economy(
                player_stats, enemy_stats, "always_fight", rng, potions_small=1, potions_large=1
            )
            assert result["result"] in sc.OUTCOMES


# ---------------------------------------------------------------------------
# simulate_progression_session_economy — интеграционные проверки
# ---------------------------------------------------------------------------


def test_economy_disabled_never_grants_loot_gold_or_potions():
    rng = random.Random(1)
    checkpoint_rng = random.Random(1_000_001)
    trajectory, _checkpoints = sce.simulate_progression_session_economy(
        60, "priority_str_vit", rng, checkpoint_rng, stat_points_per_level=2, economy_enabled=False
    )
    for row in trajectory:
        assert row["loot_dropped"] is None
        assert row["gold_balance_after"] == 0
        assert row["potions_owned_small"] == 0
        assert row["potions_owned_large"] == 0
        assert row["potion_used"] == "none"


def test_economy_enabled_eventually_grants_loot_and_gold():
    rng = random.Random(1)
    checkpoint_rng = random.Random(1_000_001)
    trajectory, _checkpoints = sce.simulate_progression_session_economy(
        60, "priority_str_vit", rng, checkpoint_rng, stat_points_per_level=2, economy_enabled=True
    )
    assert any(row["loot_dropped"] is not None for row in trajectory)
    assert any(row["gold_balance_after"] > 0 for row in trajectory)


def test_economy_enabled_respects_potion_caps_throughout_session():
    rng = random.Random(100)
    checkpoint_rng = random.Random(1_100_000)
    trajectory, _checkpoints = sce.simulate_progression_session_economy(
        300, "priority_str_vit", rng, checkpoint_rng, stat_points_per_level=2, economy_enabled=True
    )
    for row in trajectory:
        assert 0 <= row["potions_owned_small"] <= sce.SMALL_POTION_CAP
        assert 0 <= row["potions_owned_large"] <= sce.LARGE_POTION_CAP
        assert row["gold_balance_after"] >= 0


def test_economy_disabled_matches_engine_rng_stream_until_first_divergence():
    # Ключевое свойство, ради которого control-прогон не дублирует боевой
    # цикл (см. docstring модуля): без зелий в инвентаре новый шаг не жрёт
    # rng, поэтому первый бой economy=False идёт БИТ-В-БИТ той же
    # последовательностью бросков, что и оригинальный движок sc.simulate_single_fight.
    from scripts import simulate_combat as sc

    player_stats = {"hp_max": 50, "strength": 10, "agility": 5, "luck": 2}
    enemy_stats = sc.ENEMY_PRESETS["wolf"]

    rng_economy = random.Random(9)
    result_economy = sce.simulate_single_fight_economy(
        player_stats, enemy_stats, "always_fight", rng_economy, potions_small=0, potions_large=0
    )

    rng_original = random.Random(9)
    result_original = sc.simulate_single_fight(player_stats, enemy_stats, "always_fight", rng_original)

    assert result_economy["result"] == result_original["result"]
    assert result_economy["player_hp_remaining"] == result_original["player_hp_remaining"]
    assert result_economy["enemy_hp_remaining"] == result_original["enemy_hp_remaining"]
    assert result_economy["rounds"] == result_original["rounds"]


# ---------------------------------------------------------------------------
# Диагностика раннего этапа (docs/notes.md) — гипотеза о цене входа
# ---------------------------------------------------------------------------


def _row(level, enemy, gold_after, potions_small, potions_large, potion_used, fight_index=1):
    return {
        "fight_index": fight_index,
        "level": level,
        "enemy": enemy,
        "gold_balance_after": gold_after,
        "potions_owned_small": potions_small,
        "potions_owned_large": potions_large,
        "potion_used": potion_used,
    }


def test_avg_gold_returns_none_for_empty_rows():
    assert sce._avg_gold([]) is None


def test_avg_gold_averages_gold_balance_after():
    rows = [_row(1, "mouse", 2, 0, 0, "none"), _row(1, "mouse", 6, 0, 0, "none")]
    assert sce._avg_gold(rows) == 4


def test_first_potion_ownership_fight_finds_first_row_with_any_potion():
    trajectory = [
        _row(1, "mouse", 0, 0, 0, "none", fight_index=1),
        _row(1, "mouse", 8, 0, 0, "none", fight_index=2),
        _row(1, "mouse", 0, 1, 0, "none", fight_index=3),  # куплено перед этим боем
        _row(2, "wolf", 0, 1, 0, "small", fight_index=4),
    ]
    assert sce._first_potion_ownership_fight(trajectory) == 3


def test_first_potion_ownership_fight_none_if_never_owned():
    trajectory = [_row(1, "mouse", 0, 0, 0, "none", fight_index=i) for i in range(1, 5)]
    assert sce._first_potion_ownership_fight(trajectory) is None


def test_potion_use_rate_wolf_boar_ignores_mouse():
    rows = [
        _row(1, "mouse", 0, 0, 0, "small"),  # не считается — мышь
        _row(1, "wolf", 0, 0, 0, "small"),
        _row(1, "boar", 0, 0, 0, "none"),
    ]
    assert sce._potion_use_rate_wolf_boar(rows) == 50.0  # 1 из 2 wolf/boar боёв


def test_potion_use_rate_wolf_boar_none_when_no_relevant_fights():
    rows = [_row(1, "mouse", 0, 0, 0, "none")]
    assert sce._potion_use_rate_wolf_boar(rows) is None


def test_early_game_diagnostics_print_smoke(capsys):
    # Не проверяем точный формат вывода построчно — только что функция не
    # падает на реальных данных сессии и печатает ожидаемые заголовки.
    rng = random.Random(1)
    checkpoint_rng = random.Random(1_000_001)
    trajectory, _checkpoints = sce.simulate_progression_session_economy(
        60, "priority_str_vit", rng, checkpoint_rng, stat_points_per_level=2, economy_enabled=True
    )
    sce.print_early_game_diagnostics([{"seed": 1, "trajectory": trajectory}], session_fights=60)
    output = capsys.readouterr().out
    assert "Ранний этап" in output
    assert "1й_бой_с_зельем" in output
