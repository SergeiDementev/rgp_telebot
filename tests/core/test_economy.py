"""Тесты core/economy.py — лут, золото, зелья (docs/notes.md, п.30)."""

import pytest

from core import economy as ec


# ---------------------------------------------------------------------------
# Лут
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "roll,expected_name",
    [
        (1, "mouse_pelt"),
        (45, "mouse_pelt"),
        (46, "mouse_tail"),
        (60, "mouse_tail"),
        (61, "nothing"),
        (100, "nothing"),
    ],
)
def test_resolve_loot_drop_mouse_cumulative_bands(roll, expected_name):
    name, _price = ec.resolve_loot_drop("mouse", roll)
    assert name == expected_name


def test_resolve_loot_drop_returns_matching_price():
    name, price = ec.resolve_loot_drop("wolf", 1)
    assert name == "wolf_fang"
    assert price == 8


def test_resolve_loot_drop_nothing_has_zero_price():
    name, price = ec.resolve_loot_drop("boar", 100)
    assert name == "nothing"
    assert price == 0


@pytest.mark.parametrize("roll", [1, 50, 100])
def test_resolve_loot_drop_boss_never_drops_anything(roll):
    # docs/notes.md, п.36 — финальный босс без лута, любой бросок -> "nothing".
    name, price = ec.resolve_loot_drop("boss", roll)
    assert name == "nothing"
    assert price == 0


def test_sell_loot_value_sums_by_price():
    loot = {"mouse_pelt": 14, "wolf_fang": 3}
    assert ec.sell_loot_value(loot) == 14 * 2 + 3 * 8


def test_sell_loot_value_empty_inventory():
    assert ec.sell_loot_value({}) == 0


def test_sell_loot_value_ignores_zero_counts():
    assert ec.sell_loot_value({"mouse_pelt": 0}) == 0


# ---------------------------------------------------------------------------
# Зелья — параметры
# ---------------------------------------------------------------------------


def test_potion_heal_percent_large_greater_than_small():
    assert ec.potion_heal_percent("large") > ec.potion_heal_percent("small")


def test_potion_price_large_greater_than_small():
    assert ec.potion_price("large") > ec.potion_price("small")


def test_potion_functions_reject_unknown_size():
    with pytest.raises(ValueError):
        ec.potion_heal_percent("medium")
    with pytest.raises(ValueError):
        ec.potion_price("medium")
    with pytest.raises(ValueError):
        ec.potion_cap("medium")


def test_calculate_heal_amount_matches_percent_of_hp_max():
    assert ec.calculate_heal_amount(100, "small") == 25
    assert ec.calculate_heal_amount(100, "large") == 50


def test_is_hp_at_or_below_heal_threshold():
    assert ec.is_hp_at_or_below_heal_threshold(40, 100) is True
    assert ec.is_hp_at_or_below_heal_threshold(41, 100) is False


# ---------------------------------------------------------------------------
# Выбор зелья для питья в бою
# ---------------------------------------------------------------------------


def test_choose_potion_to_drink_prefers_large():
    assert ec.choose_potion_to_drink(potions_small=3, potions_large=1) == "large"


def test_choose_potion_to_drink_falls_back_to_small():
    assert ec.choose_potion_to_drink(potions_small=2, potions_large=0) == "small"


def test_choose_potion_to_drink_none_when_empty():
    assert ec.choose_potion_to_drink(potions_small=0, potions_large=0) is None


# ---------------------------------------------------------------------------
# Покупка зелья — явный выбор размера
# ---------------------------------------------------------------------------


def test_check_can_buy_potion_ok_when_affordable_and_under_cap():
    assert ec.check_can_buy_potion(gold=100, potions_small=0, potions_large=0, size="small") is None


def test_check_can_buy_potion_not_enough_gold():
    assert ec.check_can_buy_potion(gold=0, potions_small=0, potions_large=0, size="small") == "not_enough_gold"


def test_check_can_buy_potion_cap_reached_takes_priority_over_gold():
    # Даже с горой золота — если кап уже достигнут, причина именно "cap_reached",
    # не "not_enough_gold" (бот должен показать правильное сообщение).
    reason = ec.check_can_buy_potion(gold=10_000, potions_small=0, potions_large=ec.LARGE_POTION_CAP, size="large")
    assert reason == "cap_reached"


def test_buy_potion_small_deducts_price_and_increments_count():
    gold, small, large = ec.buy_potion(gold=20, potions_small=0, potions_large=0, size="small")
    assert (gold, small, large) == (20 - ec.SMALL_POTION_PRICE, 1, 0)


def test_buy_potion_large_deducts_price_and_increments_count():
    gold, small, large = ec.buy_potion(gold=100, potions_small=0, potions_large=0, size="large")
    assert (gold, small, large) == (100 - ec.LARGE_POTION_PRICE, 0, 1)


def test_buy_potion_raises_with_reason_when_not_allowed():
    with pytest.raises(ValueError, match="not_enough_gold"):
        ec.buy_potion(gold=0, potions_small=0, potions_large=0, size="small")


def test_buy_potion_rejects_unknown_size():
    with pytest.raises(ValueError):
        ec.buy_potion(gold=1000, potions_small=0, potions_large=0, size="medium")
