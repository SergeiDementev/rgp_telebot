"""Настройки подключения к БД (docs/hardening_plan.md, этап 2).

Самодостаточный модуль: сам грузит .env при импорте (не полагается на то,
что это уже сделал кто-то другой раньше в цепочке импортов — порядок
импортов в разных местах разный, см. docs/notes.md про bot/main.py/
bot/client.py). DATABASE_URL обязателен — раньше без него тихо
подставлялся локальный SQLite-файл, и разработка с незамеченной опечаткой
в .env могла молча работать совсем на другой БД, чем сервер."""

from dotenv import load_dotenv
from pydantic import ValidationError
from pydantic_settings import BaseSettings

load_dotenv()


class DbSettings(BaseSettings):
    database_url: str


try:
    settings = DbSettings()  # type: ignore[call-arg]  # pydantic-settings берёт значения из окружения, не из аргументов конструктора
except ValidationError as error:
    missing = ", ".join(str(e["loc"][0]).upper() for e in error.errors())
    raise RuntimeError(
        f"Не заданы обязательные переменные окружения: {missing}. Добавь их в .env (см. .env.example)."
    ) from error
