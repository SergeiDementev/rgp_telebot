"""Общая инфраструктура для тестов bot/."""

import pytest

from bot.utils import _user_locks


@pytest.fixture(autouse=True)
def _reset_user_locks():
    """bot/utils.py::user_lock хранит asyncio.Lock в module-level словаре,
    живущем всё время процесса — в реальном боте один долгоживущий event
    loop (docker-compose.yml, docs/notes.md), поэтому это безопасно.
    pytest-asyncio же создаёт СВОЙ event loop на каждый тест: asyncio.Lock
    привязывается к loop'у лениво, при первом acquire — если тот же
    telegram_user_id (в тестах почти всегда один и тот же дефолтный id)
    попадётся в следующем тесте с новым loop'ом, `await lock.acquire()`
    падает с "is bound to a different event loop". Чистим словарь после
    каждого теста, чтобы process-level кеш не тёк между тестами."""
    yield
    _user_locks.clear()
