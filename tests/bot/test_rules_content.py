"""Тесты bot/rules_content.py — markdown content/rules.md -> Telegram HTML.

Тестируем через публичную parse_rules_markdown() на маленьком примере, а не
реальный content/rules.md — так тесты не завязаны на конкретный текст правил
и не сломаются при следующей его правке.

Двуязычность (docs/notes.md, блок 5) — второй блок тестов ниже проверяет
реальные content/rules.md/rules.en.md через rules_menu_title()/
rules_sections(): именно структурное соответствие между локалями (число и
порядок разделов), а не содержание текста — оно не должно совпадать, это же
перевод."""

import pytest

from bot.rules_content import parse_rules_markdown, rules_menu_title, rules_sections
from core import i18n

SAMPLE = """# Заголовок документа

## 1. Первый раздел

Обычный текст с **жирным** и `кодом`.

### Подзаголовок

| Кол1 | Кол2 |
|---|---|
| a | b |

> Цитата строка 1
> - вложенный пункт

## 2. Второй раздел

| Уровень | Очков всего | Прокачки |
|---|---|---|
| 1 | 0 | 2 |
"""


def test_parse_rules_markdown_extracts_title_and_section_titles():
    title, sections = parse_rules_markdown(SAMPLE)

    assert title == "Заголовок документа"
    assert [t for t, _ in sections] == ["1. Первый раздел", "2. Второй раздел"]


def test_bold_and_code_converted_to_html_tags():
    _title, sections = parse_rules_markdown(SAMPLE)
    _title1, body1 = sections[0]

    assert "<b>жирным</b>" in body1
    assert "<code>кодом</code>" in body1
    assert "**" not in body1
    assert "`" not in body1


def test_subheader_converted_to_bold_line():
    _title, sections = parse_rules_markdown(SAMPLE)
    _title1, body1 = sections[0]

    assert "<b>Подзаголовок</b>" in body1
    assert "### " not in body1


def test_two_column_table_becomes_bullet_line_without_header_labels():
    _title, sections = parse_rules_markdown(SAMPLE)
    _title1, body1 = sections[0]

    assert "• <b>a</b> — b" in body1


def test_wide_table_becomes_bullet_line_with_header_labels():
    _title, sections = parse_rules_markdown(SAMPLE)
    _title2, body2 = sections[1]

    assert "• <b>1</b> — Очков всего: 0, Прокачки: 2" in body2


def test_blockquote_block_wrapped_and_prefix_stripped():
    _title, sections = parse_rules_markdown(SAMPLE)
    _title1, body1 = sections[0]

    assert "<blockquote>Цитата строка 1\n- вложенный пункт</blockquote>" in body1
    assert not any(line.strip().startswith("> ") for line in body1.split("\n"))


# --- Реальные content/rules.md / content/rules.en.md, обе локали ---------
# (docs/notes.md, блок 5)


@pytest.fixture
def en_locale():
    token = i18n.set_locale("en")
    try:
        yield
    finally:
        i18n.reset_locale(token)


def test_rules_menu_title_switches_with_locale(en_locale):
    ru_token = i18n.set_locale("ru")
    try:
        title_ru = rules_menu_title()
    finally:
        i18n.reset_locale(ru_token)
    assert title_ru == "Правила игры"
    assert rules_menu_title() == "Game Rules"


def test_rules_sections_switch_with_locale(en_locale):
    sections_en = rules_sections()
    assert sections_en[0][0] == "1. Introduction"


def test_rules_sections_ru_and_en_have_identical_count_and_order():
    # Кнопки меню (bot/handlers/character.py::rules_menu_keyboard) адресуют
    # раздел числовым индексом в callback_data, не текстом заголовка — если
    # структура разъедется между языками, один и тот же индекс откроет
    # разные по смыслу разделы на разных языках.
    ru_token = i18n.set_locale("ru")
    try:
        sections_ru = rules_sections()
    finally:
        i18n.reset_locale(ru_token)
    en_token = i18n.set_locale("en")
    try:
        sections_en = rules_sections()
    finally:
        i18n.reset_locale(en_token)

    assert len(sections_ru) == len(sections_en)
    for (title_ru, _body_ru), (title_en, _body_en) in zip(sections_ru, sections_en):
        # Оба заголовка начинаются с одного и того же "N. " — единственный
        # языконезависимый инвариант структуры, который можно проверить, не
        # завязываясь на конкретный перевод.
        number_ru = title_ru.split(".", 1)[0]
        number_en = title_en.split(".", 1)[0]
        assert number_ru == number_en


def test_rules_sections_bodies_are_non_empty_html_for_both_locales():
    for locale in ("ru", "en"):
        token = i18n.set_locale(locale)
        try:
            for title, body in rules_sections():
                assert title
                assert body
                assert "##" not in body  # заголовки разделов не должны просочиться внутрь текста
        finally:
            i18n.reset_locale(token)
