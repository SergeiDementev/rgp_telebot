"""Хендлеры экрана статов и прокачки (gameplay_loop_mvp.md §4-5).

Один и тот же экран/клавиатура прокачки используется и при создании
персонажа (mode="creation" — кнопка "Начать приключение"), и при обычном
левел-апе (mode="levelup" — кнопка "Назад") — механика идентична, разный
только заголовок и кнопка выхода (§5). Различие живёт в callback_data
("allocate:<stat>" / "create_allocate:<stat>"), не в состоянии на сервере —
бот сам ничего не хранит между сообщениями.

Двуязычность (docs/notes.md, блок 3) — текст экрана статов/прокачки идёт
через core.i18n.t(), как и боевой текст в api/rendering.py (блок 2). Импорт
core.i18n из bot/ — осознанное отступление от "бот не импортирует core/"
(тонкий клиент, docs/README.md): та фраза — про игровую логику/вычисления
(core/economy.py и т.п., которые бот принципиально дублирует, а не
импортирует, см. SMALL_POTION_PRICE ниже), не про инфраструктуру текста.
core/i18n.py — чистый lookup по ключу, ничего не считает и не хранит игровое
состояние; дублировать саму реализацию t()/ContextVar в bot/ было бы просто
копипастой одного и того же кода, без выигрыша в разделении процессов (bot/
и api/ и так уже общаются только по HTTP, откуда и не зависят друг от
друга рантаймом — этот импорт остаётся compile-time зависимостью от общего
пакета в том же репозитории, не HTTP-вызовом).

Текущую локаль на время обработки колбэка выставляет bot/utils.py::
get_character_or_prompt_start (общая точка входа для всех хендлеров ниже) —
см. её докстринг."""

import html

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.client import ApiClient, ApiError
from bot.rules_content import rules_menu_title, rules_sections
from bot.utils import get_character_or_prompt_start, safe_edit_text, try_edit_message_text, welcome_text
from core import i18n

router = Router()

# Дублирует core/economy.py (docs/notes.md, п.30) — бот принципиально не
# импортирует core/ ради игровых вычислений (тонкий клиент, см. docs/
# README.md; core.i18n — исключение, см. докстринг модуля), но подписи
# кнопок покупки должны показывать цену/кап без лишнего запроса к API. При
# изменении цен/капов в core/economy.py синхронизировать вручную — тот же
# паттерн, что уже есть для DODGE_K и т.п. между scripts/simulate_combat.py
# и api/routers/combat.py.
SMALL_POTION_PRICE = 8
LARGE_POTION_PRICE = 50
SMALL_POTION_CAP = 5
LARGE_POTION_CAP = 3

# Цена продажи за штуку (core/economy.py::LOOT_ITEM_PRICES) — для строки
# лута на экране "Меню игрока" (docs/notes.md), та же дублирующая логика.
# Названия предметов (не числа) — i18n.loot_item_names() (docs/notes.md,
# блок 3): в отличие от цены, это переводимый текст, а не игровой баланс —
# тот же словарь, что уже унифицирован на стороне api/rendering.py в
# блоке 2 (i18n/ru.py, i18n/en.py), отдельной копии на боте больше нет.
LOOT_ITEM_PRICES = {
    "mouse_pelt": 2,
    "mouse_tail": 5,
    "wolf_fang": 8,
    "wolf_pelt": 20,
    "boar_tusk": 20,
    "boar_hide": 50,
}

BUY_POTION_ERROR_KEYS = {
    "not_enough_gold": "character.buy_error.not_enough_gold",
    "cap_reached": "character.buy_error.cap_reached",
}

# Названия языков в переключателе на главном экране (docs/notes.md) — не
# через core.i18n.t(): это имя языка, а не переводимая фраза (по-русски
# "Русский" остаётся "Русский" независимо от текущей локали интерфейса).
_LANGUAGE_NATIVE_NAMES = {"ru": "Русский", "en": "English"}

# Дублирует core/progression.py::BOSS_LEVEL_REQUIREMENT (docs/notes.md,
# п.58) — только для подписи кнопки "⚔️ Бросить вызов" на экране входа в
# бой с боссом (bot/handlers/combat.py::_boss_challenge_keyboard), реальную
# проверку уровня делает сервер на POST /combat/{id}/start. Порог сюда не
# гейтит ничего — рассинхрон дал бы неверную подсказку в тексте кнопки, не
# сломанную игру.
BOSS_LEVEL_REQUIREMENT = 9

_STAT_EMOJI = {"strength": "💪", "agility": "🤸", "luck": "🍀"}
_STAT_NAME_KEYS = {
    "strength": "character.stat.strength",
    "agility": "character.stat.agility",
    "luck": "character.stat.luck",
    "vitality": "character.stat.vitality",
}


def menu_screen_title() -> str:
    """"👤 Меню игрока" — заголовок и подпись кнопки одновременно (экран
    прокачки вне создания персонажа). Функция, не константа — значение
    зависит от текущей локали (core.i18n.get_locale()), выставленной на
    время обработки колбэка. Публичная (без ведущего "_") — переиспользуется
    из bot/handlers/combat.py::_post_battle_keyboard (docs/notes.md, блок 3):
    тот же набор кнопок навигации экрана персонажа, показанный после боя."""
    return i18n.t("character.menu_title")


def creation_screen_title() -> str:
    """"🧙 Создание героя" — заголовок экрана прокачки при создании
    персонажа. Публичная — переиспользуется из bot/handlers/start.py
    (start_game/reset_confirm ведут на тот же экран создания)."""
    return i18n.t("character.creation_title")


def render_stats_screen(character: dict) -> str:
    """§4: переиспользуемый экран статов персонажа.

    `nickname` экранируется через html.escape() — это имя/фамилия из
    Telegram-профиля (bot/handlers/start.py::callback.from_user.full_name),
    полностью подконтрольные пользователю, а сообщение отправляется с
    parse_mode=HTML (bot/main.py). Без экранирования `<`/`>`/`&` в имени,
    не образующие валидный Telegram-тег, роняют отправку целиком
    ("can't parse entities") — self-DoS через собственный профиль."""
    lines = [
        f"🧙 {html.escape(character['nickname'])}",
        i18n.t("character.level_line", level=character["level"]),
        i18n.t(
            "character.hp_line",
            hp_current=f"{character['hp_current']:.0f}", hp_max=f"{character['hp_max']:.0f}",
        ),
        _stat_line("strength", character["strength"]),
        _stat_line("agility", character["agility"]),
        _stat_line("luck", character["luck"]),
        i18n.t(
            "character.victory_points_line",
            victory_points=character["victory_points"], points_to_next_level=character["points_to_next_level"],
        ),
    ]
    return "\n".join(lines)


def boss_button() -> InlineKeyboardButton:
    """Кнопка финального босса — последней и на основном экране статов, и на
    постбоевой клавиатуре (docs/notes.md, пп.36-37). Активна на любом уровне
    (docs/notes.md, п.58) — ведёт на экран входа в бой с текстом и запасом
    зелий всегда; порог уровня проверяется сервером позже, на "⚔️ Бросить
    вызов" (POST /combat/{id}/start), не здесь. Публичная (без ведущего "_")
    — переиспользуется из bot/handlers/combat.py, не только здесь."""
    return InlineKeyboardButton(text=i18n.t("character.button.boss"), callback_data="search_boss_encounter")


def _language_switch_button(character_language: str) -> InlineKeyboardButton:
    """Показывает язык, НА который переключит, а не текущий (docs/notes.md)
    — привычный паттерн переключателей языка: должно быть понятно
    независимо от того, на каком языке сейчас экран. Только два
    поддерживаемых языка (core.i18n.SUPPORTED_LOCALES) — переключение
    мгновенное, без промежуточного подэкрана выбора. Единственный способ
    сменить язык — /language удалена целиком (docs/notes.md)."""
    target = next(locale for locale in i18n.SUPPORTED_LOCALES if locale != character_language)
    return InlineKeyboardButton(text=f"🌐 {_LANGUAGE_NATIVE_NAMES[target]}", callback_data="toggle_language")


def stats_screen_keyboard(character: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=i18n.t("character.button.refresh"), callback_data="refresh_stats")],
            [InlineKeyboardButton(text=i18n.t("character.button.search_encounter"), callback_data="search_encounter")],
            [InlineKeyboardButton(text=menu_screen_title(), callback_data="open_allocation")],
            [InlineKeyboardButton(text=i18n.t("character.button.rules"), callback_data="show_rules")],
            [_language_switch_button(character.get("language", i18n.DEFAULT_LOCALE))],
            [boss_button()],
        ]
    )


def rules_menu_keyboard() -> InlineKeyboardMarkup:
    """content/rules.md целиком не влезает в лимит сообщения Telegram (4096
    символов) — показываем меню разделов, а не текст сразу (bot/rules_content.py).

    Разделы — на текущей локали (bot/rules_content.py::rules_sections(),
    docs/notes.md, блок 5); callback_data адресует раздел числовым
    индексом, не текстом заголовка — порядок и количество разделов между
    ru/en обязаны совпадать (tests/bot/test_rules_content.py), иначе один
    и тот же индекс открывал бы разные по смыслу разделы на разных языках."""
    rows = [
        [InlineKeyboardButton(text=title, callback_data=f"rules_section:{index}")]
        for index, (title, _body) in enumerate(rules_sections())
    ]
    rows.append([InlineKeyboardButton(text=i18n.t("character.button.back"), callback_data="back_to_stats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rules_section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=i18n.t("rules.button.back_to_sections"), callback_data="show_rules")]]
    )


def _stat_line(stat: str, value) -> str:
    return i18n.t("character.stat_line", emoji=_STAT_EMOJI[stat], name=i18n.t(_STAT_NAME_KEYS[stat]), value=value)


def _vitality_line(vitality, hp_max) -> str:
    return i18n.t(
        "character.vitality_line",
        name=i18n.t(_STAT_NAME_KEYS["vitality"]), value=vitality, hp_max=f"{hp_max:.0f}",
    )


def _render_loot_item(name: str, count: int) -> str:
    display_name = i18n.loot_item_names().get(name, name)
    price = LOOT_ITEM_PRICES.get(name, 0)
    if count == 1:
        return i18n.t("character.loot_item_single", name=display_name, price=price)
    return i18n.t("character.loot_item_multiple", name=display_name, count=count, total_price=price * count)


def _render_loot_line(loot: dict) -> str:
    items = [_render_loot_item(name, count) for name, count in loot.items() if count > 0]
    if not items:
        return i18n.t("character.loot_empty")
    return i18n.t("character.loot_line", items=", ".join(items))


def _render_potions_line(potions_small: int, potions_large: int) -> str:
    parts = []
    if potions_small > 0:
        parts.append(i18n.t("character.potion_count", name=i18n.t("combat.potion.small_label"), count=potions_small))
    if potions_large > 0:
        parts.append(i18n.t("character.potion_count", name=i18n.t("combat.potion.large_label"), count=potions_large))
    if not parts:
        return i18n.t("character.potions_empty")
    return i18n.t("character.potions_line", items=", ".join(parts))


def render_allocation_screen(character: dict, *, title: str, mode: str) -> str:
    """mode="creation" — прежний простой макет (у нового персонажа физически
    не может быть золота/лута/зелий, docs/gameplay_loop_mvp.md §5). mode=
    "levelup" — "Меню игрока" (docs/notes.md, п.30): статы → победные
    очки/золото/очки прокачки → лут → зелья."""
    if mode == "creation":
        return "\n".join(
            [
                title,
                i18n.t("character.unspent_points_line", unspent_stat_points=character["unspent_stat_points"]),
                "",
                _stat_line("strength", character["strength"]),
                _stat_line("agility", character["agility"]),
                _stat_line("luck", character["luck"]),
                _vitality_line(character["vitality"], character["hp_max"]),
            ]
        )

    lines = [
        i18n.t("character.level_line", level=character["level"]),
        _stat_line("strength", character["strength"]),
        _stat_line("agility", character["agility"]),
        _stat_line("luck", character["luck"]),
        _vitality_line(character["vitality"], character["hp_max"]),
        "",
        i18n.t(
            "character.victory_points_line",
            victory_points=character["victory_points"], points_to_next_level=character["points_to_next_level"],
        ),
    ]
    if character["unspent_stat_points"] > 0:
        lines.append(i18n.t("character.unspent_points_available_line", unspent_stat_points=character["unspent_stat_points"]))
    lines.append("")
    lines.append(i18n.t("character.gold_line", gold=character["gold"]))
    lines.append("")
    lines.append(_render_loot_line(character["loot"]))
    lines.append(_render_potions_line(character["potions_small"], character["potions_large"]))
    return "\n".join(lines)


def _stat_button(prefix: str, stat: str) -> InlineKeyboardButton:
    name = i18n.t(_STAT_NAME_KEYS[stat])
    return InlineKeyboardButton(text=i18n.t("character.allocate_button", name=name), callback_data=f"{prefix}:{stat}")


def _buy_potion_button(size: str, potions_owned: int) -> InlineKeyboardButton:
    if size == "large":
        name, price, cap = i18n.t("combat.potion.large_label").lower(), LARGE_POTION_PRICE, LARGE_POTION_CAP
    else:
        name, price, cap = i18n.t("combat.potion.small_label").lower(), SMALL_POTION_PRICE, SMALL_POTION_CAP
    status = i18n.t("character.potion_cap_reached") if potions_owned >= cap else i18n.t("character.potion_price", price=price)
    return InlineKeyboardButton(
        text=i18n.t("character.buy_potion_button", name=name, status=status), callback_data=f"buy_potion:{size}"
    )


def allocation_keyboard(character: dict, *, mode: str) -> InlineKeyboardMarkup:
    """mode: "creation" | "levelup" — определяет префикс callback_data и
    нижние кнопки. Три разных паттерна видимости на экране "Меню игрока"
    (docs/gameplay_loop_mvp.md §5) — не унифицировать:
    - "+1 <стат>" — исчезает целиком, если очков нет (как и раньше).
    - "Продать весь лут" — исчезает целиком, если лут пуст.
    - "Купить зелье" — ВСЕГДА видима, меняется только подпись (цена / "уже
      максимум") — покупка часто цель, к которой копится золото, прятать
      кнопку означало бы прятать сам ориентир."""
    prefix = "create_allocate" if mode == "creation" else "allocate"
    rows = []
    if character["unspent_stat_points"] > 0:
        rows.append([_stat_button(prefix, "strength"), _stat_button(prefix, "agility")])
        rows.append([_stat_button(prefix, "luck"), _stat_button(prefix, "vitality")])
    if mode == "creation":
        rows.append([InlineKeyboardButton(text=i18n.t("character.button.start_adventure"), callback_data="finish_creation")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if any(count > 0 for count in character["loot"].values()):
        rows.append([InlineKeyboardButton(text=i18n.t("character.button.sell_loot"), callback_data="sell_loot")])
    # Каждая кнопка зелья — своей строкой, не парой в одной (docs/notes.md):
    # текст с ценой не помещался при двух кнопках в ряд.
    rows.append([_buy_potion_button("small", character["potions_small"])])
    rows.append([_buy_potion_button("large", character["potions_large"])])
    rows.append([InlineKeyboardButton(text=i18n.t("character.button.back"), callback_data="back_to_stats")])
    # Только на экране "Меню игрока", не при создании — во время creation
    # ещё нечего обнулять (docs/notes.md, п.12).
    rows.append([InlineKeyboardButton(text=i18n.t("character.button.reset"), callback_data="reset_request")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "show_rules")
async def show_rules(callback: CallbackQuery) -> None:
    # Локаль на этот момент — best-effort по профилю Telegram (bot/utils.py::
    # set_locale_from_telegram_profile, docs/notes.md, блок 4): этот хендлер
    # не запрашивает персонажа (нет api-параметра), rules_menu_title()/
    # rules_sections() читают её напрямую из core.i18n.get_locale().
    await callback.message.edit_text(
        i18n.t("rules.menu_header", title=rules_menu_title()), reply_markup=rules_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rules_section:"))
async def show_rules_section(callback: CallbackQuery) -> None:
    index = int(callback.data.split(":", 1)[1])
    title, body = rules_sections()[index]
    await callback.message.edit_text(f"<b>{title}</b>\n\n{body}", reply_markup=rules_section_keyboard())
    await callback.answer()


@router.callback_query(F.data == "open_allocation")
async def open_allocation(callback: CallbackQuery, api: ApiClient) -> None:
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
    await callback.message.edit_text(
        render_allocation_screen(character, title=menu_screen_title(), mode="levelup"),
        reply_markup=allocation_keyboard(character, mode="levelup"),
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_stats")
@router.callback_query(F.data == "refresh_stats")
async def back_to_stats(callback: CallbackQuery, api: ApiClient) -> None:
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
    await safe_edit_text(callback.message, render_stats_screen(character), reply_markup=stats_screen_keyboard(character))
    await callback.answer()


@router.callback_query(F.data == "toggle_language")
async def toggle_language(callback: CallbackQuery, api: ApiClient) -> None:
    """Переключатель языка на главном экране персонажа (docs/notes.md) —
    основной способ смены языка: та же кнопочная механика, что и у
    остальных кнопок этого экрана (edit_text того же сообщения, не новое
    сообщение). Только два поддерживаемых языка (core.i18n.SUPPORTED_
    LOCALES) — переключает сразу на противоположный, без промежуточного
    выбора.

    Обновляет ОБА постоянных сообщения игрока — то, на котором физически
    нажали (callback.message — это main_message, кнопка живёт только на
    stats_screen_keyboard), и welcome-сообщение по сохранённому
    welcome_message_id (его самого под рукой нет, редактируем по id через
    try_edit_message_text). Если редактирование welcome не удалось
    (недоступно/устарело/ещё не было ни одного /start после раскатки этого
    поля) — не роняем операцию, обновляем то, что получилось, и всё равно
    подтверждаем успех через callback.answer() (как и просили).

    Заодно self-heal main_message_id (docs/notes.md) — если персонаж попал
    сюда, минуя явный /start (например, сразу после создания через
    finish_creation, где id уже закреплён отдельно, но на случай будущих
    путей без этого) или id устарел, здесь он в любом случае приводится в
    соответствие с текущим сообщением: дёшево (тот же вызов API, что и для
    языка), а /start в следующий раз будет знать, что удалять."""
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
    current = character.get("language", i18n.DEFAULT_LOCALE)
    new_language = next(locale for locale in i18n.SUPPORTED_LOCALES if locale != current)
    await api.set_language(character["id"], new_language)
    # Локаль на этот момент — от СТАРОГО character["language"] (выставлена
    # get_character_or_prompt_start выше); экран должен перерисоваться на
    # НОВОМ языке.
    i18n.set_locale(new_language)
    character["language"] = new_language

    await safe_edit_text(callback.message, render_stats_screen(character), reply_markup=stats_screen_keyboard(character))

    welcome_message_id = character.get("welcome_message_id")
    if welcome_message_id is not None:
        await try_edit_message_text(callback.bot, callback.message.chat.id, welcome_message_id, welcome_text())

    await api.set_message_ids(character["id"], main_message_id=callback.message.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith("allocate:"))
async def allocate_levelup(callback: CallbackQuery, api: ApiClient) -> None:
    stat = callback.data.split(":", 1)[1]
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
    try:
        result = await api.allocate_point(character["id"], stat)
    except ApiError:
        await callback.answer(i18n.t("character.allocate_error.no_points"), show_alert=True)
        return
    updated = result["character"]
    await callback.message.edit_text(
        render_allocation_screen(updated, title=menu_screen_title(), mode="levelup"),
        reply_markup=allocation_keyboard(updated, mode="levelup"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("create_allocate:"))
async def allocate_creation(callback: CallbackQuery, api: ApiClient) -> None:
    stat = callback.data.split(":", 1)[1]
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
    try:
        result = await api.allocate_point(character["id"], stat)
    except ApiError:
        await callback.answer(i18n.t("character.allocate_error.no_points"), show_alert=True)
        return
    updated = result["character"]
    await callback.message.edit_text(
        render_allocation_screen(updated, title=creation_screen_title(), mode="creation"),
        reply_markup=allocation_keyboard(updated, mode="creation"),
    )
    await callback.answer()


@router.callback_query(F.data == "finish_creation")
async def finish_creation(callback: CallbackQuery, api: ApiClient) -> None:
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
    await callback.message.edit_text(render_stats_screen(character), reply_markup=stats_screen_keyboard(character))
    # docs/notes.md — первое закрепление main_message_id за этим персонажем
    # (тот же принцип, что и в bot/handlers/start.py::reset_confirm): само
    # сообщение — edit, не новый message_id, но именно здесь у СВЕЖЕГО
    # персонажа (start_game) main_message_id ещё None. welcome_message_id не
    # трогаем — отдельного приветственного сообщения в этом флоу нет, оно
    # появится только на следующем явном /start.
    await api.set_message_ids(character["id"], main_message_id=callback.message.message_id)
    await callback.answer()


@router.callback_query(F.data == "sell_loot")
async def sell_loot(callback: CallbackQuery, api: ApiClient) -> None:
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
    result = await api.sell_loot(character["id"])
    updated = result["character"]
    await callback.message.edit_text(
        render_allocation_screen(updated, title=menu_screen_title(), mode="levelup"),
        reply_markup=allocation_keyboard(updated, mode="levelup"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_potion:"))
async def buy_potion(callback: CallbackQuery, api: ApiClient) -> None:
    size = callback.data.split(":", 1)[1]
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
    try:
        result = await api.buy_potion(character["id"], size)
    except ApiError as error:
        message = i18n.t(BUY_POTION_ERROR_KEYS.get(error.detail, "character.buy_error.generic"))
        await callback.answer(message, show_alert=True)
        return
    updated = result["character"]
    await callback.message.edit_text(
        render_allocation_screen(updated, title=menu_screen_title(), mode="levelup"),
        reply_markup=allocation_keyboard(updated, mode="levelup"),
    )
    await callback.answer()
