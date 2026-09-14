"""Статичные данные мобов — content/enemies.json (результат этапа 2 калибровки)."""

import json
from pathlib import Path

_CONTENT_PATH = Path(__file__).resolve().parent.parent / "content" / "enemies.json"

with open(_CONTENT_PATH, encoding="utf-8") as _f:
    ENEMY_STATS: dict = json.load(_f)


def get_enemy_stats(enemy_type: str) -> dict:
    return ENEMY_STATS[enemy_type]
