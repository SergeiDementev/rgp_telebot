# Multi-stage: сборочные инструменты (build-essential/libpq-dev) остаются
# только в builder-стадии — не попадают в финальный образ. Так наличие/
# отсутствие готовых wheel-пакетов под конкретную версию Python не важно:
# при необходимости пересоберётся из исходников прямо здесь.
FROM python:3.14-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.14-slim

WORKDIR /app

COPY --from=builder /install /usr/local

# Только то, что реально нужно в рантайме (docs/, scripts/, tests/, data/
# — см. .dockerignore) — content/, i18n/ и migrations/ обязательны:
# первое читает api/enemy_content.py и bot/rules_content.py, второе —
# core/i18n.py::t() (docs/notes.md, двуязычность ru/en), третье — alembic
# на старте api-контейнера (см. docker-compose.yml).
COPY api/ api/
COPY bot/ bot/
COPY core/ core/
COPY db/ db/
COPY content/ content/
COPY i18n/ i18n/
COPY migrations/ migrations/
COPY alembic.ini .

# Разумный дефолт (docker run без явной команды) — реальная команда для
# каждого сервиса задаётся в docker-compose.yml (api/bot делят один образ).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
