"""Тесты bot/rules_content.py — markdown content/rules.md -> Telegram HTML.

Тестируем через публичную parse_rules_markdown() на маленьком примере, а не
реальный content/rules.md — так тесты не завязаны на конкретный текст правил
и не сломаются при следующей его правке.
"""

from bot.rules_content import parse_rules_markdown

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
