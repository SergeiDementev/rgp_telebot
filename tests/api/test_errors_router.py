"""Тесты /errors и catch-all обработчика необработанных исключений
(docs/hardening_plan.md, этап 6, п.2)."""

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_db, require_api_key
from api.errors import register_error_handlers
from api.routers.errors import router as errors_router
from db.models import ErrorLog
from tests.api.conftest import override_get_db


def make_client(db_session_factory) -> TestClient:
    app = FastAPI()
    app.include_router(errors_router)

    # Роутер, который всегда падает — проверить catch-all обработчик живым
    # запросом, не вызовом функции-обработчика напрямую.
    broken_router = APIRouter()

    @broken_router.get("/broken")
    def broken() -> None:
        raise ValueError("deliberately broken for the test")

    app.include_router(broken_router)

    register_error_handlers(app, session_factory=db_session_factory)
    app.dependency_overrides[get_db] = override_get_db(db_session_factory)
    app.dependency_overrides[require_api_key] = lambda: None
    # raise_server_exceptions=False — иначе TestClient сам перебрасывает
    # необработанное исключение для отладки, даже когда catch-all
    # обработчик (api/errors.py) уже построил нормальный ответ: в реальном
    # сервере (uvicorn) эта раздвоенность не возникает, это только нюанс
    # тестового клиента. Проверено эмпирически перед тем, как чинить тесты.
    return TestClient(app, raise_server_exceptions=False)


def test_report_error_writes_row_with_source_bot(db_session_factory):
    client = make_client(db_session_factory)

    response = client.post(
        "/errors",
        json={"error_type": "ApiError", "message": "boom", "context": {"telegram_user_id": 1}},
    )
    assert response.status_code == 204

    db = db_session_factory()
    rows = db.query(ErrorLog).all()
    assert len(rows) == 1
    assert rows[0].source == "bot"
    assert rows[0].error_type == "ApiError"
    assert rows[0].message == "boom"
    assert rows[0].context == {"telegram_user_id": 1}
    db.close()


def test_report_error_ignores_client_supplied_source(db_session_factory):
    # source не поле схемы (api/schemas/errors.py::ErrorReportRequest) —
    # даже если его прислать, сервер не доверяет клиенту и пишет "bot" сам.
    client = make_client(db_session_factory)

    response = client.post(
        "/errors",
        json={"source": "api", "error_type": "X", "message": "x"},
    )
    assert response.status_code == 204

    db = db_session_factory()
    row = db.query(ErrorLog).one()
    assert row.source == "bot"
    db.close()


def test_report_error_defaults_context_and_traceback(db_session_factory):
    client = make_client(db_session_factory)

    response = client.post("/errors", json={"error_type": "X", "message": "x"})
    assert response.status_code == 204

    db = db_session_factory()
    row = db.query(ErrorLog).one()
    assert row.context == {}
    assert row.traceback is None
    db.close()


def test_unhandled_exception_returns_internal_error_code(db_session_factory):
    client = make_client(db_session_factory)

    response = client.get("/broken")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal.unexpected_error"


def test_unhandled_exception_is_logged_with_source_api(db_session_factory):
    client = make_client(db_session_factory)

    client.get("/broken")

    db = db_session_factory()
    row = db.query(ErrorLog).filter(ErrorLog.source == "api").one()
    assert row.error_type == "ValueError"
    assert row.message == "deliberately broken for the test"
    assert row.context == {"path": "/broken", "method": "GET"}
    assert row.traceback is not None
    assert "ValueError" in row.traceback
    db.close()


def test_game_error_still_returns_its_own_code_not_internal(db_session_factory):
    # Проверка, что catch-all не перехватывает GameError по MRO (он должен
    # резолвиться более специфичным обработчиком) — require_api_key здесь
    # НЕ переопределён (в отличие от make_client выше), чтобы спровоцировать
    # настоящий GameError("auth.invalid_api_key") через реальный роутер.
    app = FastAPI()
    app.include_router(errors_router)
    register_error_handlers(app, session_factory=db_session_factory)
    app.dependency_overrides[get_db] = override_get_db(db_session_factory)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/errors", json={"error_type": "X", "message": "x"}, headers={"X-Internal-Api-Key": "wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"

    db = db_session_factory()
    assert db.query(ErrorLog).count() == 0  # GameError — не "необработанная", в error_log не попадает
    db.close()
