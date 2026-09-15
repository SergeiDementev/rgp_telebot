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

import os
from typing import Any, Optional

import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "dev-local-key")


class ApiError(Exception):
    """Ответ API 4xx/5xx — status_code и detail из тела ответа."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class ApiClient:
    def __init__(
        self,
        base_url: str = API_BASE_URL,
        api_key: str = INTERNAL_API_KEY,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url, headers={"X-Internal-Api-Key": api_key}, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ApiClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        telegram_user_id: Optional[int] = None,
        json: Optional[dict] = None,
    ) -> dict:
        headers = {}
        if telegram_user_id is not None:
            headers["X-Telegram-User-Id"] = str(telegram_user_id)
        response = await self._client.request(method, path, json=json, headers=headers)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text
            raise ApiError(response.status_code, detail)
        if response.status_code == 204:
            return {}
        return response.json()

    # --- character (backend_plan.md §5) ---

    async def create_character(self, telegram_user_id: int, nickname: str) -> dict:
        return await self._request(
            "POST", "/character", json={"telegram_user_id": telegram_user_id, "nickname": nickname}
        )

    async def get_character(self, telegram_user_id: int) -> dict:
        return await self._request("GET", f"/character/{telegram_user_id}")

    async def allocate_point(self, character_id: int, stat: str) -> dict:
        return await self._request(
            "POST", f"/character/{character_id}/allocate_point", json={"stat": stat}
        )

    async def delete_character(self, telegram_user_id: int) -> None:
        await self._request("DELETE", f"/character/{telegram_user_id}")

    # --- encounter / combat ---

    async def search_encounter(self, telegram_user_id: int) -> dict:
        return await self._request("POST", "/encounter/search", telegram_user_id=telegram_user_id)

    async def start_combat(self, telegram_user_id: int, combat_session_id: int) -> dict:
        return await self._request(
            "POST", f"/combat/{combat_session_id}/start", telegram_user_id=telegram_user_id
        )

    async def confirm_combat(self, telegram_user_id: int, combat_session_id: int, decision: str) -> dict:
        return await self._request(
            "POST",
            f"/combat/{combat_session_id}/confirm",
            telegram_user_id=telegram_user_id,
            json={"decision": decision},
        )

    async def take_turn(self, telegram_user_id: int, combat_session_id: int) -> dict:
        return await self._request(
            "POST", f"/combat/{combat_session_id}/turn", telegram_user_id=telegram_user_id
        )

    async def flee_decision(self, telegram_user_id: int, combat_session_id: int, decision: str) -> dict:
        return await self._request(
            "POST",
            f"/combat/{combat_session_id}/flee_decision",
            telegram_user_id=telegram_user_id,
            json={"decision": decision},
        )

    async def get_combat_session(self, telegram_user_id: int, combat_session_id: int) -> dict:
        return await self._request(
            "GET", f"/combat/{combat_session_id}", telegram_user_id=telegram_user_id
        )
