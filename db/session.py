"""Подключение к БД и фабрика сессий для api/.

DATABASE_URL — единственный источник строки подключения (docs/notes.md) —
migrations/env.py импортирует его отсюда же, alembic.ini его не задаёт.
По умолчанию (если DATABASE_URL не задан) — локальный SQLite-файл, как и
раньше, ничего не ломается без .env. Реальная эксплуатация — PostgreSQL
через DATABASE_URL в .env (см. .env.example); ORM/миграции не завязаны на
конкретную СУБД, отличается только эта строка и connect_args ниже.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Единственное место, где грузится .env, общее для api/, alembic (через
# migrations/env.py, который импортирует DATABASE_URL отсюда) и scripts/.
load_dotenv()

DB_PATH = Path(__file__).resolve().parent.parent / "rpg.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")

# check_same_thread — только у SQLite (один физический файл, FastAPI бьёт
# из разных потоков); для Postgres этот kwarg не существует и упал бы.
# pool_pre_ping — защита от "server closed the connection unexpectedly" на
# сетевой БД (Postgres может закрыть простаивающее соединение); для
# SQLite-файла это no-op, не мешает.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI-зависимость: одна сессия на запрос, закрывается по завершении."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
