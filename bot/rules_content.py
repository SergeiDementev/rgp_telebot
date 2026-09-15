"""content/rules.md -> текст для Telegram (bot задан на parse_mode=HTML, main.py).

content/rules.md — единый источник и для человека (обычный markdown), и для
бота: здесь только минимальное преобразование в то, что понимает Telegram
(<b>/<code>/<blockquote> — из немногих тегов, которые разрешает Bot API), и
сборка markdown-таблиц в читаемые строки — таблиц Telegram не поддерживает
вообще. Файл целиком (~7000 символов) не влезает в лимит одного сообщения
Telegram (4096 символов), поэтому режется на секции по `## ` — ровно так же,
как секции самого документа; кнопка "Правила" открывает меню, а не текст
целиком (bot/handlers/character.py).
"""

import re
from pathlib import Path

_CONTENT_PATH = Path(__file__).resolve().parent.parent / "content" / "rules.md"

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+?)`")
_SUBHEADER_RE = re.compile(r"(?m)^### (.+)$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s\-:|]+\|$")


def _split_table_row(line: str) -> list:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _render_table_row(headers: list, cells: list) -> str:
    if len(cells) == 1:
        return f"• {cells[0]}"
    if len(cells) == 2:
        return f"• <b>{cells[0]}</b> — {cells[1]}"
    pairs = ", ".join(f"{headers[i]}: {cells[i]}" for i in range(1, len(cells)))
    return f"• <b>{cells[0]}</b> — {pairs}"


def _convert_blocks(text: str) -> str:
    """Построчно сворачивает markdown-таблицы в читаемые строки и
    blockquote-блоки (`> `) в <blockquote>. Инлайновые ** и ` уже должны быть
    превращены в HTML до вызова этой функции — так проще, чем лезть внутрь
    уже разобранных ячеек/строк."""
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("|") and stripped.endswith("|") and i + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(
            lines[i + 1].strip()
        ):
            headers = _split_table_row(stripped)
            i += 2  # пропустить строку-заголовок и строку-разделитель
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                out.append(_render_table_row(headers, _split_table_row(lines[i])))
                i += 1
            continue

        if stripped.startswith("> "):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith("> "):
                quote_lines.append(lines[i].strip()[2:])
                i += 1
            out.append("<blockquote>" + "\n".join(quote_lines) + "</blockquote>")
            continue

        out.append(line)
        i += 1

    return "\n".join(out)


def _markdown_to_telegram_html(body: str) -> str:
    body = _BOLD_RE.sub(r"<b>\1</b>", body)
    body = _CODE_RE.sub(r"<code>\1</code>", body)
    body = _SUBHEADER_RE.sub(r"<b>\1</b>", body)
    body = _convert_blocks(body)
    body = re.sub(r"\n{3,}", "\n\n", body)  # не больше одной пустой строки подряд
    return body.strip()


def parse_rules_markdown(source: str):
    """-> (заголовок документа, [(заголовок раздела, HTML-текст раздела), ...])."""
    chunks = re.split(r"(?m)^## (.+)$", source)
    preamble = chunks[0]
    title_match = re.search(r"(?m)^# (.+)$", preamble)
    menu_title = title_match.group(1) if title_match else "Правила игры"

    sections = []
    for j in range(1, len(chunks), 2):
        section_title = chunks[j].strip()
        section_body = _markdown_to_telegram_html(chunks[j + 1])
        sections.append((section_title, section_body))
    return menu_title, sections


with open(_CONTENT_PATH, encoding="utf-8") as _f:
    RULES_MENU_TITLE, RULES_SECTIONS = parse_rules_markdown(_f.read())
