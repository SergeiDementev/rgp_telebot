"""Настройки API-процесса (docs/hardening_plan.md, этап 2).

Самодостаточный модуль, сам грузит .env при импорте (см. db/settings.py —
тот же приём, по той же причине). INTERNAL_API_KEY обязателен: раньше
без него тихо подставлялся "dev-local-key", и бот с API могли незаметно
согласиться на дефолтный ключ вместо настоящего из .env."""

from dotenv import load_dotenv
from pydantic import ValidationError
from pydantic_settings import BaseSettings

load_dotenv()


class ApiSettings(BaseSettings):
    internal_api_key: str


try:
    settings = ApiSettings()  # type: ignore[call-arg]  # pydantic-settings берёт значения из окружения, не из аргументов конструктора
except ValidationError as error:
    missing = ", ".join(str(e["loc"][0]).upper() for e in error.errors())
    raise RuntimeError(
        f"Не заданы обязательные переменные окружения: {missing}. Добавь их в .env (см. .env.example)."
    ) from error
