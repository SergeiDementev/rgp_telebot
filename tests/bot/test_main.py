"""Тесты bot/main.py — сборка Dispatcher, проверка обязательного токена."""

import pytest

from bot.main import build_dispatcher, main

pytestmark = pytest.mark.asyncio


async def test_build_dispatcher_registers_all_handler_routers():
    dp = build_dispatcher()
    assert len(dp.sub_routers) == 3


async def test_main_raises_without_telegram_bot_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        await main()
