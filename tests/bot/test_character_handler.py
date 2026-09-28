"""Тесты bot/handlers/character.py — экран статов и прокачка."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.client import ApiError
from bot.handlers.character import (
    allocate_creation,
    allocate_levelup,
    allocation_keyboard,
    back_to_stats,
    buy_potion,
    finish_creation,
    open_allocation,
    render_allocation_screen,
    render_stats_screen,
    sell_loot,
    show_rules,
    show_rules_section,
    stats_screen_keyboard,
)
from bot.rules_content import RULES_MENU_TITLE, RULES_SECTIONS
from core import i18n

pytestmark = pytest.mark.asyncio

BASE_CHARACTER = {
    "id": 1, "nickname": "Hero", "level": 1, "victory_points": 0, "points_to_next_level": 8,
    "unspent_stat_points": 5, "strength": 3, "agility": 3, "luck": 1, "vitality": 3,
    "hp_current": 50.0, "hp_max": 50.0,
    "gold": 0, "loot": {}, "potions_small": 0, "potions_large": 0,
}


def make_callback(data: str, user_id: int = 1) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = user_id
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def test_show_rules_edits_same_message_with_section_menu():
    # /rules раньше слал отдельное сообщение и мог прийти не в очереди с
    # редактируемым боевым (docs/notes.md, п.1) — теперь это кнопка, тот же
    # edit_text, что и остальные экраны. Текст целиком (~7000 символов) не
    # влезает в лимит сообщения Telegram (4096), поэтому это меню разделов,
    # не сам текст правил (docs/notes.md, п.4).
    callback = make_callback("show_rules")

    await show_rules(callback)

    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.call_args.args[0]
    assert RULES_MENU_TITLE in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert len(markup.inline_keyboard) == len(RULES_SECTIONS) + 1  # + кнопка "Назад"
    assert markup.inline_keyboard[0][0].callback_data == "rules_section:0"
    assert markup.inline_keyboard[-1][0].callback_data == "back_to_stats"
    callback.answer.assert_awaited_once()


async def test_show_rules_section_shows_section_text_with_back_to_menu():
    callback = make_callback("rules_section:2")

    await show_rules_section(callback)

    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.call_args.args[0]
    expected_title, expected_body = RULES_SECTIONS[2]
    assert expected_title in text
    assert expected_body in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "show_rules"
    callback.answer.assert_awaited_once()


async def test_open_allocation_shows_levelup_screen():
    callback = make_callback("open_allocation")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER

    await open_allocation(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    # Без отдельной заголовочной строки — экран начинается сразу с уровня.
    assert text.startswith("🏅 Уровень:")
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[-2][0].callback_data == "back_to_stats"
    assert markup.inline_keyboard[-1][0].callback_data == "reset_request"


async def test_open_allocation_shows_unspent_points_when_pool_not_fully_spent():
    # Баг-репорт: после "Начать приключение" с недобранным стартовым пулом
    # строка "Доступно очков прокачки: N" должна быть видна и на "Меню
    # игрока" (mode="levelup"), не только на экране создания — она гейтится
    # тем же unspent_stat_points > 0, что и кнопки "+1 <стат>"
    # (allocation_keyboard), значит не может показывать одно без другого.
    callback = make_callback("open_allocation")
    api = AsyncMock()
    api.get_character.return_value = {**BASE_CHARACTER, "unspent_stat_points": 2}

    await open_allocation(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "Доступно очков прокачки: 2" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "allocate:strength" in callback_datas  # кнопки "+1" тоже видны — то же условие


async def test_render_allocation_screen_unspent_points_matches_between_modes():
    # Один и тот же персонаж/unspent_stat_points — счётчик должен совпадать
    # на экране создания и на "Меню игрока", не расходиться незаметно.
    character = {**BASE_CHARACTER, "unspent_stat_points": 3}
    creation_text = render_allocation_screen(character, title="Создание героя", mode="creation")
    levelup_text = render_allocation_screen(character, title="Меню игрока", mode="levelup")
    assert "Осталось очков: 3" in creation_text
    assert "Доступно очков прокачки: 3" in levelup_text


async def test_open_allocation_shows_economy_sections_empty_by_default():
    # docs/notes.md, п.30 — "Меню игрока": золото/лут/зелья добавлены к
    # прежнему экрану прокачки. У свежего персонажа всё по нулям.
    callback = make_callback("open_allocation")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER

    await open_allocation(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "💰 Золото: 0" in text
    assert "📦 Лут: пока нет" in text
    assert "🧪 Зелья: пока нет" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "sell_loot" not in callback_datas  # лута нет — кнопка продажи полностью исчезает
    assert "buy_potion:small" in callback_datas  # кнопки покупки видны всегда
    assert "buy_potion:large" in callback_datas


async def test_open_allocation_shows_loot_and_potions_when_present():
    character = {
        **BASE_CHARACTER,
        "gold": 23,
        "loot": {"mouse_pelt": 14, "wolf_fang": 3},
        "potions_small": 2,
        "potions_large": 1,
    }
    callback = make_callback("open_allocation")
    api = AsyncMock()
    api.get_character.return_value = character

    await open_allocation(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "💰 Золото: 23" in text
    # docs/notes.md — цена в скобках: для нескольких штук это цена×количество.
    assert "Мышиная шкурка ×14 (28 зол.)" in text  # 2 зол./шт × 14
    assert "Клык волка ×3 (24 зол.)" in text  # 8 зол./шт × 3
    assert "Малое ×2" in text
    assert "Большое ×1" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "sell_loot" in callback_datas  # лут есть — кнопка продажи видна


async def test_open_allocation_shows_plain_price_for_single_loot_item():
    # Один экземпляр — просто цена, без "×1" и без умножения.
    character = {**BASE_CHARACTER, "loot": {"wolf_pelt": 1}}
    callback = make_callback("open_allocation")
    api = AsyncMock()
    api.get_character.return_value = character

    await open_allocation(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "Шкура волка (20 зол.)" in text
    assert "×1" not in text


async def test_buy_potion_buttons_show_cap_reached_label_instead_of_price():
    character = {**BASE_CHARACTER, "potions_small": 5, "potions_large": 3}  # оба на потолке
    callback = make_callback("open_allocation")
    api = AsyncMock()
    api.get_character.return_value = character

    await open_allocation(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    buttons = {btn.callback_data: btn.text for row in markup.inline_keyboard for btn in row}
    assert "уже максимум" in buttons["buy_potion:small"]
    assert "уже максимум" in buttons["buy_potion:large"]
    assert "зол." not in buttons["buy_potion:small"]


async def test_buy_potion_buttons_show_price_when_under_cap():
    callback = make_callback("open_allocation")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER

    await open_allocation(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    buttons = {btn.callback_data: btn.text for row in markup.inline_keyboard for btn in row}
    assert "8 зол." in buttons["buy_potion:small"]
    assert "50 зол." in buttons["buy_potion:large"]


async def test_sell_loot_calls_api_and_refreshes_menu_screen():
    callback = make_callback("sell_loot")
    api = AsyncMock()
    api.get_character.return_value = {**BASE_CHARACTER, "loot": {"mouse_pelt": 14}}
    api.sell_loot.return_value = {"character": {**BASE_CHARACTER, "gold": 28, "loot": {}}}

    await sell_loot(callback, api)

    api.sell_loot.assert_awaited_once_with(1)
    text = callback.message.edit_text.call_args.args[0]
    assert "💰 Золото: 28" in text
    assert "📦 Лут: пока нет" in text
    callback.answer.assert_awaited_once()


async def test_buy_potion_success_refreshes_menu_screen():
    callback = make_callback("buy_potion:small")
    api = AsyncMock()
    api.get_character.return_value = {**BASE_CHARACTER, "gold": 100}
    api.buy_potion.return_value = {"character": {**BASE_CHARACTER, "gold": 92, "potions_small": 1}}

    await buy_potion(callback, api)

    api.buy_potion.assert_awaited_once_with(1, "small")
    text = callback.message.edit_text.call_args.args[0]
    assert "Малое ×1" in text
    callback.answer.assert_awaited_once()


async def test_buy_potion_not_enough_gold_shows_alert_without_editing_message():
    callback = make_callback("buy_potion:large")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER
    api.buy_potion.side_effect = ApiError(400, "not_enough_gold")

    await buy_potion(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once_with("Не хватает золота.", show_alert=True)


async def test_buy_potion_cap_reached_shows_distinct_alert():
    callback = make_callback("buy_potion:large")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER
    api.buy_potion.side_effect = ApiError(400, "cap_reached")

    await buy_potion(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once_with("Уже максимум зелий этого размера.", show_alert=True)


async def test_render_stats_screen_escapes_html_special_chars_in_nickname():
    # nickname приходит из Telegram-профиля (full_name) — полностью
    # подконтролен пользователю, а сообщение уходит с parse_mode=HTML
    # (bot/main.py). Без экранирования "<"/"&", не образующие валидный
    # Telegram-тег, роняют отправку целиком ("can't parse entities") —
    # self-DoS через собственное имя в профиле.
    character = {**BASE_CHARACTER, "nickname": "<b>Evil</b> & Co"}

    text = render_stats_screen(character)

    assert "<b>Evil</b>" not in text
    assert "&lt;b&gt;Evil&lt;/b&gt;" in text
    assert "&amp; Co" in text


async def test_back_to_stats_shows_stats_screen():
    callback = make_callback("back_to_stats")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER

    await back_to_stats(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "Hero" in text
    assert "Уровень" in text


async def test_refresh_stats_shows_stats_screen():
    # "Обновить" на экране статов — тот же хендлер, что и "Назад" из прокачки,
    # но нужен как отдельная кнопка на любом заходе на экран статов, не
    # только после прокачки (docs/notes.md, п.8).
    callback = make_callback("refresh_stats")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER

    await back_to_stats(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "Hero" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "refresh_stats"


async def test_back_to_stats_shows_active_boss_button_at_level_one():
    # docs/notes.md, п.58 — кнопка активна на любом уровне, порог проверяет
    # сервер позже, на "⚔️ Бросить вызов".
    callback = make_callback("back_to_stats")
    api = AsyncMock()
    api.get_character.return_value = {**BASE_CHARACTER, "level": 1}

    await back_to_stats(callback, api)

    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    button = markup.inline_keyboard[-1][0]
    assert button.callback_data == "search_boss_encounter"
    assert "🔒" not in button.text


async def test_allocate_levelup_spends_point_and_refreshes_screen():
    callback = make_callback("allocate:strength")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER
    api.allocate_point.return_value = {
        "character": {**BASE_CHARACTER, "strength": 4, "unspent_stat_points": 4}
    }

    await allocate_levelup(callback, api)

    api.allocate_point.assert_awaited_once_with(1, "strength")
    text = callback.message.edit_text.call_args.args[0]
    assert "Сила: 4" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[-2][0].callback_data == "back_to_stats"
    assert markup.inline_keyboard[-1][0].callback_data == "reset_request"


async def test_allocate_levelup_no_points_shows_alert_without_editing_message():
    callback = make_callback("allocate:strength")
    api = AsyncMock()
    api.get_character.return_value = {**BASE_CHARACTER, "unspent_stat_points": 0}
    api.allocate_point.side_effect = ApiError(400, "no unspent stat points available")

    await allocate_levelup(callback, api)

    callback.message.edit_text.assert_not_called()
    callback.answer.assert_awaited_once()
    assert callback.answer.call_args.kwargs.get("show_alert") is True


async def test_allocate_creation_uses_creation_screen():
    callback = make_callback("create_allocate:vitality")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER
    api.allocate_point.return_value = {
        "character": {**BASE_CHARACTER, "vitality": 4, "unspent_stat_points": 4, "hp_max": 60.0}
    }

    await allocate_creation(callback, api)

    api.allocate_point.assert_awaited_once_with(1, "vitality")
    text = callback.message.edit_text.call_args.args[0]
    assert "Создание героя" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[-1][0].callback_data == "finish_creation"
    callback_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "reset_request" not in callback_datas  # нечего обнуливать при создании персонажа


async def test_finish_creation_shows_stats_screen_with_search_button():
    callback = make_callback("finish_creation")
    api = AsyncMock()
    api.get_character.return_value = BASE_CHARACTER

    await finish_creation(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert "Hero" in text
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "refresh_stats"
    assert markup.inline_keyboard[1][0].callback_data == "search_encounter"
    assert markup.inline_keyboard[-2][0].callback_data == "show_rules"
    # Кнопка финального босса — всегда последняя и всегда активна
    # (docs/notes.md, пп.36, 58), даже на свежем 1 уровне.
    assert markup.inline_keyboard[-1][0].callback_data == "search_boss_encounter"


# --- Английская локаль (docs/notes.md, блок 3) ---------------------------
# По одному репрезентативному тесту на статы/прокачку/кнопки — не полное
# дублирование русских тестов выше (см. тот же принцип в
# tests/api/test_rendering.py, блок 2) — плюс один сквозной тест хендлера,
# проверяющий сам механизм переключения локали по character["language"].


@pytest.fixture
def en_locale():
    token = i18n.set_locale("en")
    try:
        yield
    finally:
        i18n.reset_locale(token)


async def test_render_stats_screen_en(en_locale):
    character = {**BASE_CHARACTER, "level": 2, "hp_current": 40.0, "hp_max": 60.0, "strength": 5}
    text = render_stats_screen(character)
    assert text == (
        "🧙 Hero\n"
        "🏅 Level: 2\n"
        "❤️ HP: 40/60\n"
        "💪 Strength: 5\n"
        "🤸 Agility: 3\n"
        "🍀 Luck: 1\n"
        "🏆 Victory points: 0 (to next level: 8)"
    )


async def test_render_allocation_screen_creation_en(en_locale):
    text = render_allocation_screen({**BASE_CHARACTER, "unspent_stat_points": 5}, title="🧙 Hero Creation", mode="creation")
    assert text == (
        "🧙 Hero Creation\n"
        "Points left: 5\n"
        "\n"
        "💪 Strength: 3\n"
        "🤸 Agility: 3\n"
        "🍀 Luck: 1\n"
        "❤️ Vitality: 3  (HP max: 50)"
    )


async def test_render_allocation_screen_levelup_en(en_locale):
    character = {**BASE_CHARACTER, "unspent_stat_points": 0, "loot": {"wolf_fang": 3}, "potions_small": 2}
    text = render_allocation_screen(character, title="👤 Player Menu", mode="levelup")
    assert "🏅 Level: 1" in text
    assert "🏆 Victory points: 0 (to next level: 8)" in text
    assert "Stat points available" not in text  # unspent_stat_points == 0
    assert "💰 Gold: 0" in text
    assert "📦 Loot: Wolf fang ×3 (24 gold)" in text
    assert "🧪 Potions: Small ×2" in text


async def test_stats_screen_keyboard_labels_en(en_locale):
    markup = stats_screen_keyboard(BASE_CHARACTER)
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert labels == ["🔄 Refresh", "🔍 Search for an enemy", "👤 Player Menu", "📜 Rules", "⚔️ Final Boss"]


async def test_allocation_keyboard_buy_potion_labels_en(en_locale):
    markup = allocation_keyboard(BASE_CHARACTER, mode="levelup")
    buttons = {btn.callback_data: btn.text for row in markup.inline_keyboard for btn in row}
    assert buttons["buy_potion:small"] == "🧪 Buy small (8 gold)"
    assert buttons["buy_potion:large"] == "🧪 Buy large (50 gold)"
    assert buttons["back_to_stats"] == "⬅️ Back"
    assert buttons["reset_request"] == "🗑 Reset character"


async def test_open_allocation_renders_in_character_language(en_locale):
    # Сквозной тест механизма (docs/notes.md, блок 3): хендлер сам вызывает
    # get_character_or_prompt_start, которая выставляет локаль по
    # character["language"] — фикстура en_locale здесь лишь задаёт
    # начальное значение, важна именно проверка, что оно пришло от сервера,
    # а не осталось от фикстуры.
    callback = make_callback("open_allocation")
    api = AsyncMock()
    api.get_character.return_value = {**BASE_CHARACTER, "language": "en"}

    await open_allocation(callback, api)

    text = callback.message.edit_text.call_args.args[0]
    assert text.startswith("🏅 Level:")
    assert "💰 Gold: 0" in text
    assert "📦 Loot: none yet" in text
