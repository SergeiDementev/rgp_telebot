"""Тесты core/i18n.py — механизм локали (contextvar, t()).

Тесты t() ниже подкладывают свои временные ключи через monkeypatch, не
полагаются на реальное содержимое TRANSLATIONS — оно наполняется по мере
блоков 2-5 (docs/notes.md) и мониторить его текстом здесь незачем,
дословная проверка боевых строк — в tests/api/test_rendering.py.
enemy_names()/loot_item_names() — исключение, у них проверяется реальное
содержимое i18n/ru.py и i18n/en.py напрямую, раз они появились в блоке 2."""

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
    # Осознанно, не молчаливый fallback (docs/notes.md) — неизвестный ключ
    # должен падать заметно, не тихо показывать игроку пустоту.
    with pytest.raises(KeyError):
        i18n.t("does.not.exist")


def test_enemy_names_returns_ru_forms_by_default():
    names = i18n.enemy_names("wolf")
    assert names["nom_cap"] == "Волк"
    assert names["dodge_verb"] == "увернулся"


def test_enemy_names_switches_with_locale():
    token = i18n.set_locale("en")
    try:
        names = i18n.enemy_names("wolf")
        assert names["nom_cap"] == "Wolf"
        assert names["dodge_verb"] == "dodged"
    finally:
        i18n.reset_locale(token)


def test_loot_item_names_switches_with_locale():
    assert i18n.loot_item_names()["wolf_fang"] == "Клык волка"
    token = i18n.set_locale("en")
    try:
        assert i18n.loot_item_names()["wolf_fang"] == "Wolf Fang"
    finally:
        i18n.reset_locale(token)

