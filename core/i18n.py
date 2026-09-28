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


def t(key: str, **kwargs) -> str:
    """Текст по ключу для текущей локали (get_locale()), с подстановкой
    kwargs через str.format(). Неизвестный ключ — KeyError, не молчаливый
    fallback на пустую строку: пока словари в i18n/ru.py и i18n/en.py не
    наполнены (блоки 2-5), любой реальный вызов t() должен падать заметно,
    не тихо показывать игроку пустоту."""
    from i18n import en as _en
    from i18n import ru as _ru

    catalogs = {"ru": _ru.TRANSLATIONS, "en": _en.TRANSLATIONS}
    catalog = catalogs.get(get_locale(), catalogs[DEFAULT_LOCALE])
    template = catalog[key]
    return template.format(**kwargs) if kwargs else template


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
