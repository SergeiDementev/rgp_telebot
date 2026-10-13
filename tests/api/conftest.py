"""Общая инфраструктура для тестов api/: изолированная БД на тест.

По умолчанию — SQLite, свой временный файл на тест (быстро, без установки
чего-либо). Если задан POSTGRES_TEST_URL (docs/hardening_plan.md, этап 1,
шаг 5 — выставляется только в .github/workflows/ci.yml) — тесты идут
против настоящего PostgreSQL, схему которого перед запуском создаёт
`alembic upgrade head` (та же команда, что при живом развёртывании), не
`Base.metadata.create_all()` — так проверяется и сама цепочка миграций,
не только код api/. Изоляция между тестами в этом режиме — очистка всех
таблиц после каждого теста (в порядке, безопасном для внешних ключей), не
пересоздание схемы: дешевле, а схема уже доказанно построена миграциями."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.session import Base

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")


@pytest.fixture(scope="session")
def _postgres_engine():
    engine = create_engine(POSTGRES_TEST_URL)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session_factory(tmp_path, request):
    if POSTGRES_TEST_URL:
        engine = request.getfixturevalue("_postgres_engine")
        testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        yield testing_session_local
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
        return

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield testing_session_local
    engine.dispose()


def override_get_db(db_session_factory):
    def _override():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    return _override
