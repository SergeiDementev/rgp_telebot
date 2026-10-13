"""Настройки бот-процесса (docs/hardening_plan.md, этап 2).

Самодостаточный модуль, сам грузит .env при импорте — не полагается на
порядок импортов в bot/main.py (там `from bot.client import ApiClient`
раньше стояло ДО собственного load_dotenv() этого файла, поэтому
API_BASE_URL/INTERNAL_API_KEY из .env при обычном запуске `python -m
bot.main` на самом деле никогда не подхватывались, тихо откатываясь на
дефолт — тот же класс проблемы, из-за которой весь этот этап и затеян).

TELEGRAM_BOT_TOKEN/INTERNAL_API_KEY обязательны. API_BASE_URL — не
секрет, оставлен с дефолтом на локальный api/: неверный адрес здесь
падает сразу и явно (connection error на первом же запросе), не тихо, в
отличие от токена/ключа."""

from dotenv import load_dotenv
from pydantic import ValidationError
from pydantic_settings import BaseSettings

load_dotenv()


class BotSettings(BaseSettings):
    telegram_bot_token: str
    internal_api_key: str
    api_base_url: str = "http://127.0.0.1:8000"


try:
    settings = BotSettings()  # type: ignore[call-arg]  # pydantic-settings берёт значения из окружения, не из аргументов конструктора
except ValidationError as error:
    missing = ", ".join(str(e["loc"][0]).upper() for e in error.errors())
    raise RuntimeError(
        f"Не заданы обязательные переменные окружения: {missing}. Добавь их в .env (см. .env.example)."
    ) from error
