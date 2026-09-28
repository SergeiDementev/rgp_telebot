"""Инфраструктура двуязычности ru/en (docs/notes.md) — механизм, без самих
текстов (те живут в i18n/ru.py, i18n/en.py).

Локаль хранится в `contextvars.ContextVar`, не передаётся параметром через
каждый вызов — осознанное решение дизайна: `t()` можно звать из глубины
любой цепочки вызовов `api/rendering.py`, не протаскивая `language` через
сигнатуру каждой промежуточной функции. Кто и когда выставляет текущую
локаль на время обработки запроса — на стороне `api/` см.
`api/dependencies.py::get_localized_character`, на стороне `bot/` —
следующие блоки.

ContextVar, не глобальная переменная — принципиально для asyncio/FastAPI:
Starlette выделяет новый `contextvars.Context` на каждый входящий запрос
(проверено эмпирически перед реализацией), поэтому значение, выставленное
для одного запроса/пользователя, не просачивается в другой параллельный
запрос — обычная глобальная переменная в асинхронном сервере с несколькими
одновременными пользователями для этого не годится."""

from __future__ import annotations

import contextvars

DEFAULT_LOCALE = "ru"
SUPPORTED_LOCALES = ("ru", "en")

_current_locale: contextvars.ContextVar[str] = contextvars.ContextVar(
    "locale", default=DEFAULT_LOCALE
)


def get_locale() -> str:
    return _current_locale.get()


def set_locale(locale: str) -> contextvars.Token:
    """Возвращает Token — передать в reset_locale(), если вызывающему коду
    важно явно вернуть предыдущее значение. В основном сценарии (один
    contextvars.Context на один HTTP-запрос) не требуется — следующий
    запрос в любом случае получит чистый DEFAULT_LOCALE, не унаследует
    это значение."""
    return _current_locale.set(locale)


def reset_locale(token: contextvars.Token) -> None:
    _current_locale.reset(token)


def _locale_module():
    """Модуль i18n/ru.py или i18n/en.py для текущей локали — общая точка
    входа для t()/enemy_names()/loot_item_names(), чтобы выбор каталога по
    get_locale() не дублировался в каждой из них."""
    from i18n import en as _en
    from i18n import ru as _ru

    modules = {"ru": _ru, "en": _en}
    return modules.get(get_locale(), modules[DEFAULT_LOCALE])


def t(key: str, **kwargs) -> str:
    """Текст по ключу для текущей локали (get_locale()), с подстановкой
    kwargs через str.format(). Неизвестный ключ — KeyError, не молчаливый
    fallback на пустую строку: любой реальный вызов t() должен падать
    заметно, не тихо показывать игроку пустоту."""
    template = _locale_module().TRANSLATIONS[key]
    return template.format(**kwargs) if kwargs else template


def enemy_names(enemy_type: str) -> dict:
    """Грамматические формы имени противника для текущей локали
    (docs/notes.md, блок 2) — общий набор ключей в обеих локалях
    (nom_cap/nom_low/acc_cap/acc_low/gen_low/ins_cap/dodge_verb/
    alive_adj/fled_verb): в ru.py формы разные (падежи/род), в en.py всё
    совпадает с одним именем (английский не склоняется) — api/rendering.py
    читает оба словаря одинаково, без ветвления по локали."""
    return _locale_module().ENEMY_NAMES[enemy_type]


def loot_item_names() -> dict:
    """Названия предметов добычи для текущей локали (api/rendering.py —
    строка добычи в конце боя)."""
    return _locale_module().LOOT_ITEM_NAMES


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение существительного по числу — три формы (например,
    "1 очко" / "2 очка" / "5 очков"), не общий CLDR-движок, а минимальная
    своя логика под конкретные места использования (наполнение — блок 3).
    Стандартное правило: последняя цифра 1, кроме 11, -> one; последняя
    цифра 2-4, кроме 12-14, -> few; иначе -> many. `n` берётся по модулю —
    отрицательные значения в игре не встречаются, но формула определена
    для них так же, как для положительных."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
