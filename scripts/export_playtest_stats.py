"""Выгружает статистику боёв и прокачки в CSV для анализа (docs/notes.md) —
по запросу плейтестера после прохождения до 10 уровня.

Один ряд = одна завершённая боевая сессия, в хронологическом порядке.
Очки победы и уровень "на момент боя" не хранятся в БД как история — они
пересчитываются заново по накопленной сумме наград (core.progression),
что валидно только если сессии идут непрерывно от создания персонажа без
сбросов между ними (сейчас так и есть).

По умолчанию читает из БД, на которую указывает DATABASE_URL (db/session.py
— тот же источник правды, что и у самого приложения, PostgreSQL или SQLite,
без разницы). --db <путь> — разовое исключение: читать конкретный SQLite-
файл напрямую (например, архивный rpg.db после перехода на Postgres,
docs/notes.md) вместо настроенной БД.

Запуск: python -m scripts.export_playtest_stats [--db rpg.db] [--character-id 1]
"""

import argparse
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import progression as pr
from db.models import CombatSession
from db.session import SessionLocal

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


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


def _open_session(db_override: str):
    """--db задан -> отдельный движок на конкретный SQLite-файл (архив).
    Иначе -> та же SessionLocal, что и у приложения (db/session.py,
    DATABASE_URL) — один источник правды, не второй способ подключения."""
    if db_override is None:
        return SessionLocal()
    engine = create_engine(f"sqlite:///{db_override}", connect_args={"check_same_thread": False})
    return sessionmaker(bind=engine)()


def export(db_override: str, character_id: int, out_path: Path) -> int:
    import csv

    db = _open_session(db_override)
    try:
        sessions = (
            db.query(CombatSession)
            .filter(CombatSession.character_id == character_id, CombatSession.status == "finished")
            .order_by(CombatSession.created_at)
            .all()
        )
    finally:
        db.close()

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
        for i, session in enumerate(sessions, start=1):
            reward = pr.calculate_battle_reward(session.result, session.enemy_type)
            victory_points += reward
            duration = (session.updated_at - session.created_at).total_seconds()
            metrics = _turn_log_metrics(session.turn_log)
            writer.writerow({
                "battle_number": i,
                "session_id": session.id,
                "created_at": session.created_at,
                "duration_seconds": round(duration, 1),
                "enemy_type": session.enemy_type,
                "result": session.result,
                "reward_points": reward,
                "victory_points_after": victory_points,
                "level_after": pr.calculate_level_for_points(victory_points),
                **metrics,
            })

    return len(sessions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=None, help="Разовое чтение конкретного SQLite-файла вместо DATABASE_URL")
    parser.add_argument("--character-id", type=int, default=1)
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = DATA_DIR / f"playtest_stats_{timestamp}.csv"

    count = export(args.db, args.character_id, out_path)
    print(f"Экспортировано {count} завершённых боёв -> {out_path}")
