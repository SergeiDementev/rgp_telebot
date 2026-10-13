"""Конфигурация pytest для всего проекта.

docs/hardening_plan.md, этап 2 — db/api/bot теперь требуют обязательные
переменные окружения без дефолтов (DATABASE_URL/INTERNAL_API_KEY/
TELEGRAM_BOT_TOKEN, см. db/settings.py, api/settings.py, bot/settings.py).
Настоящие значения тестам не нужны — выставляем заглушки здесь, ДО того,
как тестовые модули успеют импортировать db/api/bot и упереться в ошибку
валидации. pytest гарантированно загружает этот файл раньше любого теста
в подкаталогах (включая tests/api/conftest.py и сами тестовые модули).

setdefault, не прямое присваивание — чтобы не перетирать реально заданные
значения (например, при локальном прогоне tests/api против настоящего
Postgres через POSTGRES_TEST_URL, см. tests/api/conftest.py и
docs/README.md — DATABASE_URL в этом сценарии всё равно не используется
самим приложением, но пусть окружение остаётся предсказуемым)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("INTERNAL_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
