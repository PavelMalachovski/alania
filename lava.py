"""Клиент lava.top: счёт на оплату и его статус.

API: https://gate.lava.top, ключ — заголовок X-Api-Key. Счёт создаётся под
конкретного покупателя (email обязателен: lava.top шлёт на него чек, а для
курса и игры — ещё и доступ). Вебхуков бот не принимает: статус счёта
опрашивает фоновая задача (payments.py) — так не нужен публичный адрес на
Railway, бот остаётся на polling."""

import logging
import os
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://gate.lava.top"

# Офферы в кабинете lava.top (GET /api/v2/products?feedVisibility=ALL).
# Цена живёт там, бот отправляет только id оффера и валюту.
OFFERS = {
    "session": "9acf85b6-d7a5-4fec-95b8-226361e38066",  # Поддерживающая личная сессия
    "course": "8acf1977-031a-497f-9c14-49ff0021b772",   # Курс-практикум «ВЗЛОМАЙ РЕАЛЬНОСТЬ»
    "game": "43313bff-0cfb-4f12-856d-02d035033f24",     # VECHNOST — игра для пар
}
CURRENCIES = ("RUB", "EUR")

# Статусы счёта у lava.top
PENDING = ("new", "in-progress")
COMPLETED = "completed"
FAILED = ("failed", "cancelled")


class LavaError(Exception):
    """lava.top недоступен или ответил ошибкой. email_invalid — ошибка именно
    в email (400 с details.email): человека просим ввести адрес заново."""

    def __init__(self, message: str, *, email_invalid: bool = False):
        super().__init__(message)
        self.email_invalid = email_invalid


@dataclass(frozen=True)
class Invoice:
    id: str
    status: str
    payment_url: str
    amount: float
    currency: str


class LavaClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: float = 20) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    @classmethod
    def from_env(cls) -> "LavaClient | None":
        key = os.environ.get("LAVA_API_KEY", "").strip()
        return cls(key) if key else None

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        headers = {"X-Api-Key": self._api_key, "Accept": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as http:
                async with http.request(method, self._base_url + path,
                                        json=json, headers=headers) as resp:
                    try:
                        data = await resp.json(content_type=None)
                    except ValueError:
                        data = {}
                    if resp.status >= 400:
                        details = (data or {}).get("details") or {}
                        raise LavaError(
                            f"lava.top {method} {path}: {resp.status} {data}",
                            email_invalid=resp.status == 400 and "email" in details,
                        )
                    return data or {}
        except aiohttp.ClientError as e:
            raise LavaError(f"lava.top {method} {path}: {e!r}") from e
        except TimeoutError as e:
            raise LavaError(f"lava.top {method} {path}: timeout") from e

    async def create_invoice(self, email: str, offer_id: str, currency: str) -> Invoice:
        data = await self._request("POST", "/api/v2/invoice", json={
            "email": email,
            "offerId": offer_id,
            "currency": currency,
            "buyerLanguage": "RU",
        })
        amount = data.get("amountTotal") or {}
        if not data.get("id") or not data.get("paymentUrl"):
            raise LavaError(f"lava.top: в ответе нет id/paymentUrl: {data}")
        return Invoice(
            id=data["id"],
            status=data.get("status", "new"),
            payment_url=data["paymentUrl"],
            amount=float(amount.get("amount") or 0),
            currency=amount.get("currency") or currency,
        )

    async def invoice_status(self, invoice_id: str) -> str:
        data = await self._request("GET", f"/api/v1/invoices/{invoice_id}")
        return data.get("status", "")
