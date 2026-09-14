"""SQLite-подключение и фабрика сессий для api/.

SQLite для старта, без конфигурации (backend_plan.md §1) — переход на
Postgres потребует только смены DATABASE_URL, весь остальной код ORM не
завязан на конкретную СУБД.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = Path(__file__).resolve().parent.parent / "rpg.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI-зависимость: одна сессия на запрос, закрывается по завершении."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
