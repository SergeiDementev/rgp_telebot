"""Точка входа бота (aiogram, polling).

Запуск: python -m bot.main
Требует TELEGRAM_BOT_TOKEN в .env (см. .env.example) и работающий api/
(uvicorn api.main:app) на адресе из API_BASE_URL/INTERNAL_API_KEY.
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from bot.client import ApiClient
from bot.handlers import character, combat, start

load_dotenv()


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(character.router)
    dp.include_router(combat.router)
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан — добавь его в .env (см. .env.example)")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()

    async with ApiClient() as api:
        await dp.start_polling(bot, api=api)


if __name__ == "__main__":
    asyncio.run(main())
