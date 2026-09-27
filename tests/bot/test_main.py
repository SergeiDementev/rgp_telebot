"""Тесты bot/main.py — сборка Dispatcher, проверка обязательного токена."""

import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock

import pytest
from aiogram.exceptions import TelegramRetryAfter

import bot.main as bot_main
from bot.handlers import fallback
from bot.main import build_dispatcher, main

pytestmark = pytest.mark.asyncio


async def test_build_dispatcher_registers_all_handler_routers():
    # Один-единственный вызов build_dispatcher() в модуле — Router
    # aiogram можно прикрепить только к одному Dispatcher за раз, а
    # роутеры хендлеров — модульные синглтоны, общие для всех тестов
    # в процессе.
    dp = build_dispatcher()
    assert len(dp.sub_routers) == 4
    # docs/notes.md — заглушка на нераспознанный текст должна идти
    # последней, иначе она перехватила бы сообщения раньше конкретных
    # команд.
    assert dp.sub_routers[-1] is fallback.router


async def test_main_raises_without_telegram_bot_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        await main()


async def test_log_retry_after_reraises_and_logs_warning(caplog):
    # docs/notes.md — расследование flood control (429): middleware сессии
    # должен ловить TelegramRetryAfter от ЛЮБОГО метода API, писать WARNING
    # с именем метода и retry_after, и пробрасывать исключение дальше без
    # изменения поведения (aiogram сам знает, как ждать retry_after).
    method = MagicMock()
    method.__api_method__ = "sendMessage"
    error = TelegramRetryAfter(method=method, message="Too Many Requests: retry after 5", retry_after=5)

    async def make_request(bot, method):
        raise error

    with caplog.at_level(logging.WARNING, logger="bot.flood_control"):
        with pytest.raises(TelegramRetryAfter):
            await bot_main._log_retry_after(make_request, MagicMock(), method)

    messages = [record.message for record in caplog.records]
    assert any("sendMessage" in m and "retry_after=5" in m for m in messages)


async def test_log_retry_after_passes_through_successful_requests():
    method = MagicMock()

    async def make_request(bot, method):
        return "ok"

    result = await bot_main._log_retry_after(make_request, MagicMock(), method)

    assert result == "ok"


async def test_add_file_logging_adds_rotating_handler_in_project_subdir(tmp_path, monkeypatch):
    # docs/notes.md — лог должен пережить docker compose up -d --build
    # (bind mount, не writable-слой контейнера) и жить в поддиректории
    # именно этого проекта, не общесерверной.
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(bot_main, "LOG_DIR", log_dir)
    monkeypatch.setattr(bot_main, "LOG_PATH", log_dir / "bot.log")
    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    bot_main._add_file_logging()
    try:
        assert log_dir.is_dir()
        new_handlers = [h for h in root_logger.handlers if h not in handlers_before]
        assert len(new_handlers) == 1
        assert isinstance(new_handlers[0], RotatingFileHandler)
        assert new_handlers[0].baseFilename == str(log_dir / "bot.log")
    finally:
        for handler in root_logger.handlers[:]:
            if handler not in handlers_before:
                root_logger.removeHandler(handler)
                handler.close()
