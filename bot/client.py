"""Асинхронный HTTP-клиент бота к API (backend_plan.md §1, §9).

Тонкий клиент: только вызовы `api/` и разбор JSON-ответов, никакой игровой
логики — она вся на сервере (README.md, "клиент не хранит и не вычисляет
ничего игровое").

`X-Internal-Api-Key` шлётся всегда (авторизация бота). `X-Telegram-User-Id`
шлётся только там, где эндпоинту нужно знать "чей это персонаж" —
character-эндпоинты работают по explicit id/telegram_user_id в
пути/теле и этого заголовка не требуют, а encounter/combat — требуют
(`api/dependencies.get_current_character`).
"""

from typing import Any

import httpx

from bot.settings import settings

API_BASE_URL = settings.api_base_url
INTERNAL_API_KEY = settings.internal_api_key


class ApiError(Exception):
    """Ответ API 4xx/5xx — status_code и code (docs/hardening_plan.md, этап 4,
    п.1: {"error": {"code": ..., "details": {...}}}) из тела ответа.
    Фоллбэк на простой текст в code — для ответов без этой структуры
    (например, 500 без JSON-тела вообще)."""

    def __init__(self, status_code: int, code: Any, details: dict[str, Any] | None = None):
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        super().__init__(f"API error {status_code}: {code} {self.details}")


class ApiClient:
    def __init__(
        self,
        base_url: str = API_BASE_URL,
        api_key: str = INTERNAL_API_KEY,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url, headers={"X-Internal-Api-Key": api_key}, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        telegram_user_id: int | None = None,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        headers = {}
        if telegram_user_id is not None:
            headers["X-Telegram-User-Id"] = str(telegram_user_id)
        response = await self._client.request(method, path, json=json, params=params, headers=headers)
        if response.status_code >= 400:
            try:
                body: dict[str, Any] | None = response.json()
            except ValueError:
                body = None
            error = body.get("error") if body is not None else None
            if error is not None:
                raise ApiError(response.status_code, error.get("code"), error.get("details"))
            # Фоллбэк — ответ не от GameError (например, встроенная 422
            # валидация FastAPI, не наш обработчик в api/main.py, или не JSON вообще).
            raise ApiError(response.status_code, body.get("detail") if body is not None else response.text)
        if response.status_code == 204:
            return {}
        return response.json()

    # --- character (backend_plan.md §5) ---

    async def create_character(self, telegram_user_id: int, nickname: str, language: str = "ru") -> dict:
        return await self._request(
            "POST",
            "/character",
            json={"telegram_user_id": telegram_user_id, "nickname": nickname, "language": language},
        )

    async def get_character(self, telegram_user_id: int) -> dict:
        return await self._request("GET", f"/character/{telegram_user_id}")

    async def allocate_point(self, character_id: int, stat: str) -> dict:
        return await self._request("POST", f"/character/{character_id}/allocate_point", json={"stat": stat})

    async def sell_loot(self, character_id: int) -> dict:
        return await self._request("POST", f"/character/{character_id}/sell_loot")

    async def buy_potion(self, character_id: int, size: str) -> dict:
        return await self._request("POST", f"/character/{character_id}/buy_potion", json={"size": size})

    async def set_language(self, character_id: int, language: str) -> dict:
        return await self._request("POST", f"/character/{character_id}/set_language", json={"language": language})

    async def set_message_ids(
        self, character_id: int, *, welcome_message_id: int | None = None, main_message_id: int | None = None
    ) -> dict:
        """docs/notes.md — запоминает message_id двух постоянных сообщений
        игрока (приветствия/главного экрана). Частичное обновление — не
        переданное (None) поле на сервере не меняется, не путать с явным
        сбросом в null (см. api/schemas/character.py::SetMessageIdsRequest)."""
        payload = {}
        if welcome_message_id is not None:
            payload["welcome_message_id"] = welcome_message_id
        if main_message_id is not None:
            payload["main_message_id"] = main_message_id
        return await self._request("POST", f"/character/{character_id}/set_message_ids", json=payload)

    async def delete_character(self, telegram_user_id: int, reason: str) -> None:
        """`reason` — "manual_reset" | "boss_victory" (docs/notes.md, п.41):
        персонаж не удаляется физически, а архивируется (is_active=False) —
        причина нужна серверу для аналитики, не влияет на сам сброс."""
        await self._request("DELETE", f"/character/{telegram_user_id}", params={"reason": reason})

    # --- encounter / combat ---

    async def search_encounter(self, telegram_user_id: int) -> dict:
        return await self._request("POST", "/encounter/search", telegram_user_id=telegram_user_id)

    async def search_boss_encounter(self, telegram_user_id: int) -> dict:
        return await self._request("POST", "/encounter/search_boss", telegram_user_id=telegram_user_id)

    async def start_combat(self, telegram_user_id: int, combat_session_id: int) -> dict:
        return await self._request("POST", f"/combat/{combat_session_id}/start", telegram_user_id=telegram_user_id)

    async def confirm_combat(self, telegram_user_id: int, combat_session_id: int, decision: str) -> dict:
        return await self._request(
            "POST",
            f"/combat/{combat_session_id}/confirm",
            telegram_user_id=telegram_user_id,
            json={"decision": decision},
        )

    async def take_turn(self, telegram_user_id: int, combat_session_id: int, power_attack: bool = False) -> dict:
        return await self._request(
            "POST",
            f"/combat/{combat_session_id}/turn",
            telegram_user_id=telegram_user_id,
            json={"power_attack": power_attack},
        )

    async def flee_decision(self, telegram_user_id: int, combat_session_id: int, decision: str) -> dict:
        return await self._request(
            "POST",
            f"/combat/{combat_session_id}/flee_decision",
            telegram_user_id=telegram_user_id,
            json={"decision": decision},
        )

    async def use_potion(self, telegram_user_id: int, combat_session_id: int, size: str) -> dict:
        return await self._request(
            "POST",
            f"/combat/{combat_session_id}/use_potion",
            telegram_user_id=telegram_user_id,
            json={"size": size},
        )

    async def get_combat_session(self, telegram_user_id: int, combat_session_id: int) -> dict:
        return await self._request("GET", f"/combat/{combat_session_id}", telegram_user_id=telegram_user_id)

    async def resume_combat_session(self, telegram_user_id: int, combat_session_id: int) -> dict:
        """docs/notes.md, п.48 — восстановление потерянной клавиатуры боя
        (например, после удаления чата в Telegram); только чтение, ничего
        не мутирует на сервере."""
        return await self._request("GET", f"/combat/{combat_session_id}/resume", telegram_user_id=telegram_user_id)

    async def cancel_combat_session(self, telegram_user_id: int, combat_session_id: int) -> None:
        """docs/notes.md, п.51 — "⬅️ Назад" на экране входа в бой, до
        инициативы: отменяет встречу целиком, ничего в бою ещё не произошло."""
        await self._request("DELETE", f"/combat/{combat_session_id}", telegram_user_id=telegram_user_id)

    # --- журнал ошибок (docs/hardening_plan.md, этап 6, п.2) ---

    async def report_error(
        self, error_type: str, message: str, context: dict[str, Any] | None = None, traceback: str | None = None
    ) -> None:
        """Репортит необработанное исключение бота в тот же журнал, что и
        ошибки API (db.models.ErrorLog) — вызывающий код (bot/main.py)
        сам решает, что делать, если и этот вызов упадёт (например, сама
        API недоступна), эта функция не скрывает такую ошибку сама."""
        await self._request(
            "POST",
            "/errors",
            json={"error_type": error_type, "message": message, "context": context or {}, "traceback": traceback},
        )
