"""Точка входа бота (aiogram, polling).

Запуск: python -m bot.main
Требует TELEGRAM_BOT_TOKEN в .env (см. .env.example) и работающий api/
(uvicorn api.main:app) на адресе из API_BASE_URL/INTERNAL_API_KEY.
"""

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from dotenv import load_dotenv

from bot.client import ApiClient
from bot.handlers import character, combat, fallback, language, start
from bot.utils import set_locale_from_telegram_profile

load_dotenv()

# Поддиректория проекта, не общесерверная (docs/notes.md) — на сервере со
# временем могут появиться другие приложения, их логи не должны смешиваться
# с логами именно этого бота. Путь через __file__, не через cwd — тот же
# результат что при `python -m bot.main` из корня репозитория (WORKDIR /app
# в Dockerfile), что при запуске откуда-то ещё.
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_PATH = LOG_DIR / "bot.log"

_retry_after_logger = logging.getLogger("bot.flood_control")


async def _log_retry_after(make_request, bot: Bot, method):
    """Middleware сессии бота (docs/notes.md) — оборачивает КАЖДЫЙ вызов
    Telegram Bot API (sendMessage, editMessageText, answerCallbackQuery и
    т.д.), не только боевые хендлеры. Ничего не меняет в поведении —
    исключение всегда пробрасывается дальше как есть, только логируется
    WARNING с именем метода и retry_after до этого."""
    try:
        return await make_request(bot, method)
    except TelegramRetryAfter as error:
        _retry_after_logger.warning(
            "Telegram flood control: method=%s retry_after=%s", method.__api_method__, error.retry_after
        )
        raise


def _add_file_logging() -> None:
    """Файловый хендлер в ДОПОЛНЕНИЕ к stdout (docs/notes.md), не вместо
    него — docker compose logs по-прежнему работает. Переживает
    `docker compose up -d --build`: пишет в bind mount (docker-compose.yml,
    ./logs:/app/logs), не во writable-слой контейнера, который пересоздаётся
    при пересборке. RotatingFileHandler, не голый FileHandler — лог на
    долго живущем сервере иначе рос бы неограниченно."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=10_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)


async def _clear_bot_commands(bot: Bot) -> None:
    """Меню команд Telegram (иконка "/" рядом с полем ввода) — решено убрать
    (docs/notes.md): основной путь в игре и так через кнопки на игровых
    экранах (в т.ч. переключатель языка), не слэш-команды, а список команд
    в интерфейсе оказался лишним шумом. Сами команды (/start, /language,
    /reset) никуда не делись и по-прежнему работают при ручном вводе —
    меняется только их видимость в этом системном списке.

    Раньше здесь регистрировался список на три локали (docs/notes.md,
    блок 6 — set_my_commands с language_code "ru"/"en"/дефолт). Явно
    удаляем те же три регистрации, а не просто перестаём их обновлять —
    иначе список, уже выставленный на серверах Telegram с прошлых
    деплоев, остался бы висеть бесконечно, сам он не пропадёт."""
    for locale in ("ru", "en", None):
        await bot.delete_my_commands(language_code=locale)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    # Ставится на уровне диспетчера, не отдельного роутера (docs/notes.md,
    # блок 4) — покрывает все хендлеры разом, включая /start и /reset, где
    # персонаж ещё не известен вовсе. bot/utils.py::
    # set_locale_from_telegram_profile — best-effort по профилю Telegram,
    # хендлеры с точным character.language переопределяют это позже сами.
    dp.message.middleware(set_locale_from_telegram_profile)
    dp.callback_query.middleware(set_locale_from_telegram_profile)
    dp.include_router(start.router)
    dp.include_router(character.router)
    dp.include_router(combat.router)
    dp.include_router(language.router)
    # Последним (docs/notes.md) — ловит любой текст, не подошедший ни
    # одной команде/фильтру выше по цепочке.
    dp.include_router(fallback.router)
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан — добавь его в .env (см. .env.example)")

    # После проверки токена, не раньше — иначе быстрый отказ выше уже
    # создавал бы logs/bot.log и директорию под него без всякой пользы.
    _add_file_logging()

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot.session.middleware(_log_retry_after)
    await _clear_bot_commands(bot)
    dp = build_dispatcher()

    async with ApiClient() as api:
        await dp.start_polling(bot, api=api)


if __name__ == "__main__":
    asyncio.run(main())
