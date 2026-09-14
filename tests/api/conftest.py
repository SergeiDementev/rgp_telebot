"""Общая инфраструктура для тестов api/: изолированная SQLite-БД на тест."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.session import Base


@pytest.fixture()
def db_session_factory(tmp_path):
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
