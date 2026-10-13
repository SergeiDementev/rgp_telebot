"""Подключение к БД и фабрика сессий для api/.

DATABASE_URL — единственный источник строки подключения (docs/notes.md) —
migrations/env.py импортирует его отсюда же, alembic.ini его не задаёт.
Обязателен (docs/hardening_plan.md, этап 2 — db/settings.py падает понятной
ошибкой при старте, если его нет): раньше без него тихо подставлялся
локальный SQLite-файл, и разработка с незамеченной опечаткой в .env могла
молча работать совсем на другой БД, чем сервер. Реальная эксплуатация —
PostgreSQL через DATABASE_URL в .env (см. .env.example); ORM/миграции не
завязаны на конкретную СУБД, отличается только эта строка и connect_args
ниже.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from db.settings import settings

DATABASE_URL = settings.database_url

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
