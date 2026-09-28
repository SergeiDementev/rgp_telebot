"""Тесты core/i18n.py — механизм локали (contextvar, t(), плюрализация).

Словари i18n/ru.py и i18n/en.py пустые на этом этапе (docs/notes.md,
наполнение — блоки 2-5) — тесты t() подкладывают свои временные ключи через
monkeypatch, не полагаются на реальное содержимое словарей."""

import pytest

from core import i18n


def test_get_locale_defaults_to_ru():
    assert i18n.get_locale() == i18n.DEFAULT_LOCALE == "ru"


def test_set_locale_changes_get_locale_and_reset_restores_it():
    token = i18n.set_locale("en")
    try:
        assert i18n.get_locale() == "en"
    finally:
        i18n.reset_locale(token)
    assert i18n.get_locale() == "ru"


def test_t_formats_with_kwargs_for_current_locale(monkeypatch):
    from i18n import ru as ru_catalog

    monkeypatch.setitem(ru_catalog.TRANSLATIONS, "test.greeting", "Привет, {name}!")
    token = i18n.set_locale("ru")
    try:
        assert i18n.t("test.greeting", name="Мир") == "Привет, Мир!"
    finally:
        i18n.reset_locale(token)


def test_t_switches_catalog_with_current_locale(monkeypatch):
    from i18n import en as en_catalog
    from i18n import ru as ru_catalog

    monkeypatch.setitem(ru_catalog.TRANSLATIONS, "test.hello", "Привет")
    monkeypatch.setitem(en_catalog.TRANSLATIONS, "test.hello", "Hello")

    token = i18n.set_locale("ru")
    try:
        assert i18n.t("test.hello") == "Привет"
    finally:
        i18n.reset_locale(token)

    token = i18n.set_locale("en")
    try:
        assert i18n.t("test.hello") == "Hello"
    finally:
        i18n.reset_locale(token)


def test_t_raises_key_error_for_unknown_key():
    # Осознанно, не молчаливый fallback (docs/notes.md) — пока словари
    # пустые, любой реальный вызов должен падать заметно.
    with pytest.raises(KeyError):
        i18n.t("does.not.exist")


@pytest.mark.parametrize(
    "n,expected",
    [
        (1, "one"), (21, "one"), (101, "one"), (121, "one"),
        (2, "few"), (3, "few"), (4, "few"), (22, "few"), (24, "few"), (104, "few"),
        (0, "many"), (5, "many"), (10, "many"), (11, "many"), (12, "many"), (13, "many"),
        (14, "many"), (20, "many"), (25, "many"), (100, "many"), (111, "many"),
    ],
)
def test_plural_ru_selects_correct_form(n, expected):
    assert i18n.plural_ru(n, one="one", few="few", many="many") == expected


def test_plural_ru_uses_absolute_value():
    assert i18n.plural_ru(-1, one="one", few="few", many="many") == "one"
    assert i18n.plural_ru(-5, one="one", few="few", many="many") == "many"
