"""Экономика поверх боевого ядра — лут, золото, зелья (docs/notes.md, п.30).

Тот же принцип, что и `combat_mechanics.py`/`progression.py`: только чистые
функции, без побочных эффектов и без хранения состояния между вызовами.
Кубики не бросаются внутри модуля — `resolve_loot_drop` принимает уже
готовый бросок аргументом (`roll`), как `resolve_circumstance_outcome`
принимает d10 в `combat_mechanics.py`.

Единственный источник констант и правил экономики для `api/` (реальная игра)
и `scripts/simulate_combat_economy.py`/`simulate_boss.py` (калибровка) — до
2026-09-17 эти константы существовали только в симуляторе (docs/notes.md,
пп.26-29); перенесены сюда, когда экономика из черновика калибровки стала
частью самой игры (docs/notes.md, п.30).
"""

from typing import Optional

# ---------------------------------------------------------------------------
# Лут — таблица весов по мобу, откалибровано в scripts/simulate_combat_economy.py.
# (название, вес_в_процентах, цена_продажи_золото) — вес суммируется к 100 на
# каждого моба (не обязательное требование rng-выбора, но держит числа читаемыми).
# ---------------------------------------------------------------------------

LOOT_TABLE = {
    "mouse": [("mouse_pelt", 45, 2), ("mouse_tail", 15, 5), ("nothing", 40, 0)],
    "wolf": [("wolf_fang", 45, 8), ("wolf_pelt", 15, 20), ("nothing", 40, 0)],
    "boar": [("boar_tusk", 45, 20), ("boar_hide", 15, 50), ("nothing", 40, 0)],
    # Финальный босс не роняет лут (docs/notes.md, п.36) — победа сама по
    # себе конец игры, трофей за неё пока не придуман.
    "boss": [("nothing", 100, 0)],
}

# Производная от LOOT_TABLE карта цен — единственное место, где реально нужна
# цена по названию предмета (продажа лута), не пересчитывать вручную.
LOOT_ITEM_PRICES = {
    name: price for entries in LOOT_TABLE.values() for name, _weight, price in entries if name != "nothing"
}


def resolve_loot_drop(enemy_type: str, roll: int) -> tuple[str, int]:
    """Бросок на лут — независимая операция ПОСЛЕ победы, не часть исхода
    боя (как обстоятельство — отдельный бросок поверх уже готовой
    инициативы). `roll` — 1-100, вызывающий код (`api/`, симулятор) сам
    решает, как его получить (`random.randint(1, 100)` и т.п.) — этот
    модуль кубики не бросает. Веса читаются по кумулятивным границам."""
    entries = LOOT_TABLE[enemy_type]
    cumulative = 0
    for name, weight, price in entries:
        cumulative += weight
        if roll <= cumulative:
            return name, price
    # Сумма весов равна 100, а roll <= 100 по контракту — сюда дойти не
    # должны, но на случай вызова с roll > 100 отдаём последний исход честно.
    name, _weight, price = entries[-1]
    return name, price


def sell_loot_value(loot: dict) -> int:
    """Золото за весь инвентарь лута разом — простая сумма count × цена."""
    return sum(count * LOOT_ITEM_PRICES[name] for name, count in loot.items() if count > 0)


# ---------------------------------------------------------------------------
# Зелья — проценты от hp_max, покупка с капами на инвентарь.
# ---------------------------------------------------------------------------

SMALL_POTION_HEAL_PERCENT = 25
LARGE_POTION_HEAL_PERCENT = 50
SMALL_POTION_PRICE = 8
LARGE_POTION_PRICE = 50
HEAL_TRIGGER_HP_PERCENT = 40  # использовать зелье в бою, если HP/HP_max <= этот порог

SMALL_POTION_CAP = 5
LARGE_POTION_CAP = 3

POTION_SIZES = ("small", "large")


def _validate_potion_size(size: str) -> None:
    if size not in POTION_SIZES:
        raise ValueError(f"unknown potion size: {size!r}")


def potion_heal_percent(size: str) -> int:
    _validate_potion_size(size)
    return LARGE_POTION_HEAL_PERCENT if size == "large" else SMALL_POTION_HEAL_PERCENT


def potion_price(size: str) -> int:
    _validate_potion_size(size)
    return LARGE_POTION_PRICE if size == "large" else SMALL_POTION_PRICE


def potion_cap(size: str) -> int:
    _validate_potion_size(size)
    return LARGE_POTION_CAP if size == "large" else SMALL_POTION_CAP


def calculate_heal_amount(hp_max: float, size: str) -> int:
    """Округляется до целого, как и урон в combat_mechanics.py::
    calculate_damage — HP должен оставаться целым всегда, не только при
    отображении (docs/notes.md): без округления здесь HP_max, не кратный 4
    (25%/50% не делятся ровно), давал дробный остаток, который расчёт урона
    (уже целый) никогда не мог "доокруглить" обратно — он молча копился в
    hp_current/character_hp_snapshot до конца боя и дальше."""
    return round(hp_max * potion_heal_percent(size) / 100)


def is_hp_at_or_below_heal_threshold(hp: float, hp_max: float) -> bool:
    return hp / hp_max <= HEAL_TRIGGER_HP_PERCENT / 100


def choose_potion_to_drink(potions_small: int, potions_large: int) -> Optional[str]:
    """Автоматический выбор зелья ВО ВРЕМЯ БОЯ (не в магазине — там игрок
    выбирает размер явно кнопкой) — приоритет Большому, если есть. None,
    если инвентарь пуст."""
    if potions_large > 0:
        return "large"
    if potions_small > 0:
        return "small"
    return None


def check_can_buy_potion(gold: int, potions_small: int, potions_large: int, size: str) -> Optional[str]:
    """None — можно купить. Иначе причина отказа: "cap_reached" |
    "not_enough_gold" — вызывающий код (api-роутер) должен уметь показать
    игроку РАЗНУЮ причину (не хватает золота vs уже максимум), не единое
    "нельзя" (docs/gameplay_loop_mvp.md, паттерн видимости кнопок покупки)."""
    _validate_potion_size(size)
    current = potions_large if size == "large" else potions_small
    if current >= potion_cap(size):
        return "cap_reached"
    if gold < potion_price(size):
        return "not_enough_gold"
    return None


def buy_potion(gold: int, potions_small: int, potions_large: int, size: str) -> tuple[int, int, int]:
    """Покупает ОДНО зелье конкретного размера — явный выбор игрока (кнопка
    "Купить малое"/"Купить большое"), не автоматический приоритет. Бросает
    ValueError с причиной отказа, если условия не выполнены — вызывающий
    код обязан проверить `check_can_buy_potion()` заранее и вернуть понятную
    ошибку, не полагаться на исключение как штатный поток управления."""
    reason = check_can_buy_potion(gold, potions_small, potions_large, size)
    if reason is not None:
        raise ValueError(reason)
    price = potion_price(size)
    if size == "large":
        return gold - price, potions_small, potions_large + 1
    return gold - price, potions_small + 1, potions_large
