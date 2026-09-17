"""Выгружает статистику боёв и прокачки из rpg.db в CSV для анализа
(docs/notes.md) — по запросу плейтестера после прохождения до 10 уровня.

Один ряд = одна завершённая боевая сессия, в хронологическом порядке.
Очки победы и уровень "на момент боя" не хранятся в БД как история — они
пересчитываются заново по накопленной сумме наград (core.progression),
что валидно только если сессии идут непрерывно от создания персонажа без
сбросов между ними (сейчас так и есть).

Запуск: python -m scripts.export_playtest_stats [--db rpg.db] [--character-id 1]
"""

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from core import progression as pr

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _turn_log_metrics(turn_log: list) -> dict:
    initiative = next((e for e in turn_log if e["type"] == "initiative"), None)
    circumstance = next((e for e in turn_log if e["type"] == "circumstance"), None)
    strikes = [e for e in turn_log if e["type"] == "strike"]
    flee_checks = [e for e in turn_log if e["type"] == "flee_opportunity_check"]

    return {
        "turns_taken": sum(1 for e in turn_log if e["type"] == "double_strike_check"),
        "initiative_winner": initiative["first_role"] if initiative else "",
        "circumstance_outcome": circumstance["outcome"] if circumstance else "",
        "circumstance_roller": circumstance["roller_role"] if circumstance else "",
        "player_strikes": sum(1 for e in strikes if e["side"] == "player"),
        "enemy_strikes": sum(1 for e in strikes if e["side"] == "enemy"),
        "damage_dealt": sum(e["damage"] for e in strikes if e["side"] == "player"),
        "damage_taken": sum(e["damage"] for e in strikes if e["side"] == "enemy"),
        "flee_checks": len(flee_checks),
        "flee_checks_triggered": sum(1 for e in flee_checks if e["triggered"]),
    }


def export(db_path: str, character_id: int, out_path: Path) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sessions = cur.execute(
        """
        SELECT id, enemy_type, result, turn_log, created_at, updated_at
        FROM combat_sessions
        WHERE character_id = ? AND status = 'finished'
        ORDER BY created_at
        """,
        (character_id,),
    ).fetchall()
    conn.close()

    fieldnames = [
        "battle_number", "session_id", "created_at", "duration_seconds",
        "enemy_type", "result", "reward_points", "victory_points_after", "level_after",
        "turns_taken", "initiative_winner", "circumstance_outcome", "circumstance_roller",
        "player_strikes", "enemy_strikes", "damage_dealt", "damage_taken",
        "flee_checks", "flee_checks_triggered",
    ]

    victory_points = 0
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, row in enumerate(sessions, start=1):
            reward = pr.calculate_battle_reward(row["result"], row["enemy_type"])
            victory_points += reward
            duration = (_parse_dt(row["updated_at"]) - _parse_dt(row["created_at"])).total_seconds()
            metrics = _turn_log_metrics(json.loads(row["turn_log"]))
            writer.writerow({
                "battle_number": i,
                "session_id": row["id"],
                "created_at": row["created_at"],
                "duration_seconds": round(duration, 1),
                "enemy_type": row["enemy_type"],
                "result": row["result"],
                "reward_points": reward,
                "victory_points_after": victory_points,
                "level_after": pr.calculate_level_for_points(victory_points),
                **metrics,
            })

    return len(sessions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="rpg.db")
    parser.add_argument("--character-id", type=int, default=1)
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = DATA_DIR / f"playtest_stats_{timestamp}.csv"

    count = export(args.db, args.character_id, out_path)
    print(f"Экспортировано {count} завершённых боёв -> {out_path}")
