"""Тесты bot/main.py — сборка Dispatcher, проверка обязательного токена."""

import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramRetryAfter

import bot.main as bot_main
from bot.handlers import fallback
from bot.main import _bot_commands, _register_bot_commands, build_dispatcher, main
from core import i18n

pytestmark = pytest.mark.asyncio


async def test_build_dispatcher_registers_all_handler_routers():
    # Один-единственный вызов build_dispatcher() в модуле — Router
    # aiogram можно прикрепить только к одному Dispatcher за раз, а
    # роутеры хендлеров — модульные синглтоны, общие для всех тестов
    # в процессе.
    dp = build_dispatcher()
    assert len(dp.sub_routers) == 5
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


async def test_bot_commands_ru():
    token = i18n.set_locale("ru")
    try:
        descriptions = {c.command: c.description for c in _bot_commands()}
        assert descriptions == {
            "start": "Начать/продолжить игру",
            "language": "Сменить язык",
            "reset": "Обнулить персонажа",
        }
    finally:
        i18n.reset_locale(token)


async def test_bot_commands_en():
    token = i18n.set_locale("en")
    try:
        descriptions = {c.command: c.description for c in _bot_commands()}
        assert descriptions == {
            "start": "Start/continue the game",
            "language": "Change language",
            "reset": "Reset character",
        }
    finally:
        i18n.reset_locale(token)


async def test_register_bot_commands_sets_ru_en_and_default():
    # docs/notes.md, блок 6 — меню команд Telegram показывается по языку
    # КЛИЕНТА (language_code в set_my_commands), не по character.language:
    # три вызова — явный "ru", явный "en", и без language_code (дефолт для
    # прочих языков клиента, на тех же текстах, что и en — тот же принцип,
    # что и в bot/utils.py::detect_language(), "не ru -> en").
    bot = MagicMock()
    bot.set_my_commands = AsyncMock()

    await _register_bot_commands(bot)

    assert bot.set_my_commands.await_count == 3
    calls = bot.set_my_commands.call_args_list
    ru_call = next(c for c in calls if c.kwargs.get("language_code") == "ru")
    en_call = next(c for c in calls if c.kwargs.get("language_code") == "en")
    default_call = next(c for c in calls if c.kwargs.get("language_code") is None)

    ru_descriptions = {cmd.command: cmd.description for cmd in ru_call.args[0]}
    en_descriptions = {cmd.command: cmd.description for cmd in en_call.args[0]}
    default_descriptions = {cmd.command: cmd.description for cmd in default_call.args[0]}

    assert ru_descriptions == {
        "start": "Начать/продолжить игру",
        "language": "Сменить язык",
        "reset": "Обнулить персонажа",
    }
    assert en_descriptions == {
        "start": "Start/continue the game",
        "language": "Change language",
        "reset": "Reset character",
    }
    assert default_descriptions == en_descriptions


async def test_register_bot_commands_does_not_leak_locale():
    bot = MagicMock()
    bot.set_my_commands = AsyncMock()

    await _register_bot_commands(bot)

    assert i18n.get_locale() == i18n.DEFAULT_LOCALE
