"""Тесты bot/main.py — сборка Dispatcher, проверка обязательного токена."""

import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramRetryAfter

import bot.main as bot_main
from bot.handlers import fallback
from bot.main import _clear_bot_commands, build_dispatcher

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
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


def test_bot_fails_fast_without_required_env_vars(tmp_path):
    # docs/hardening_plan.md, этап 2 — bot/settings.py валидирует
    # TELEGRAM_BOT_TOKEN/INTERNAL_API_KEY при самом импорте, не откладывая
    # до первого реального использования (bot/main.py импортирует
    # bot.settings на уровне модуля). Не monkeypatch + повторный вызов
    # main() в этом же процессе — bot.settings уже импортирован и
    # закэширован (корневой tests/conftest.py выставляет заглушки до
    # коллекции тестов), повторный импорт не перевалидирует ничего;
    # нужен настоящий свежий процесс с пустым окружением, как при
    # реальном старте без .env.
    #
    # cwd — временная директория, не корень репозитория: bot/settings.py
    # сам вызывает load_dotenv(), которая иначе нашла бы настоящий .env
    # разработчика (с реальными токенами) при поиске вверх по дереву
    # каталогов и тест бы не воспроизвёл сценарий отсутствия .env вообще.
    env = {k: v for k, v in os.environ.items() if k not in ("TELEGRAM_BOT_TOKEN", "INTERNAL_API_KEY")}
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", "import bot.settings"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "TELEGRAM_BOT_TOKEN" in result.stderr
    assert "INTERNAL_API_KEY" in result.stderr


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_log_retry_after_passes_through_successful_requests():
    method = MagicMock()

    async def make_request(bot, method):
        return "ok"

    result = await bot_main._log_retry_after(make_request, MagicMock(), method)

    assert result == "ok"


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_clear_bot_commands_deletes_ru_en_and_default():
    # docs/notes.md — меню команд Telegram (иконка "/") решено убрать: явно
    # удаляем те же три регистрации, что раньше выставлял _register_bot_
    # commands (блок 6) — "ru"/"en"/дефолт, — иначе список, уже выставленный
    # на серверах Telegram с прошлых деплоев, остался бы висеть.
    bot = MagicMock()
    bot.delete_my_commands = AsyncMock()

    await _clear_bot_commands(bot)

    assert bot.delete_my_commands.await_count == 3
    language_codes = {c.kwargs.get("language_code") for c in bot.delete_my_commands.call_args_list}
    assert language_codes == {"ru", "en", None}
