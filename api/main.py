"""FastAPI-приложение — сборка роутеров (backend_plan.md §3).

Запуск: uvicorn api.main:app --reload
Swagger: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI

from api.routers.character import router as character_router
from api.routers.combat import router as combat_router
from api.routers.encounter import router as encounter_router
from db import models as _models  # noqa: F401 — регистрирует ORM-модели в Base.metadata
from db.session import Base, engine

# Без alembic на этапе MVP (backend_plan.md §10) — таблицы создаются по факту,
# если их ещё нет.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="RPG Telegram Bot API", version="0.1.0")

app.include_router(character_router)
app.include_router(encounter_router)
app.include_router(combat_router)


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok"}
