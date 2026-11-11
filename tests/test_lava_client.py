"""LavaClient против локального HTTP-сервера: путь, заголовок ключа, тело
запроса и разбор ответов/ошибок lava.top (формат ошибок снят с живого API)."""
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from lava import LavaClient, LavaError


async def _serve(routes):
    app = web.Application()
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()
    return server, LavaClient("secret-key", base_url=str(server.make_url("")))


@pytest.mark.asyncio
async def test_create_invoice_sends_key_and_body():
    seen = {}

    async def handler(request):
        seen["key"] = request.headers.get("X-Api-Key")
        seen["body"] = await request.json()
        return web.json_response({
            "id": "inv-1", "status": "new",
            "amountTotal": {"currency": "RUB", "amount": 5000},
            "paymentUrl": "https://app.lava.top/pay/inv-1",
        })

    server, client = await _serve([("POST", "/api/v2/invoice", handler)])
    try:
        inv = await client.create_invoice("a@b.ru", "offer-1", "RUB")
    finally:
        await server.close()
    assert seen["key"] == "secret-key"
    assert seen["body"] == {"email": "a@b.ru", "offerId": "offer-1",
                            "currency": "RUB", "buyerLanguage": "RU"}
    assert (inv.id, inv.status, inv.amount, inv.currency) == ("inv-1", "new", 5000.0, "RUB")
    assert inv.payment_url == "https://app.lava.top/pay/inv-1"


@pytest.mark.asyncio
async def test_invalid_email_is_flagged():
    async def handler(request):
        return web.json_response({"error": "Some input fields are invalid",
                                  "details": {"email": "must be a well-formed email address"}},
                                 status=400)

    server, client = await _serve([("POST", "/api/v2/invoice", handler)])
    try:
        with pytest.raises(LavaError) as e:
            await client.create_invoice("x", "offer-1", "RUB")
    finally:
        await server.close()
    assert e.value.email_invalid is True


@pytest.mark.asyncio
async def test_other_errors_are_not_email_errors():
    async def handler(request):
        return web.json_response({"error": "Product with offer id = 'x' not found",
                                  "details": {}}, status=404)

    server, client = await _serve([("POST", "/api/v2/invoice", handler)])
    try:
        with pytest.raises(LavaError) as e:
            await client.create_invoice("a@b.ru", "x", "RUB")
    finally:
        await server.close()
    assert e.value.email_invalid is False


@pytest.mark.asyncio
async def test_invoice_status():
    async def handler(request):
        assert request.match_info["iid"] == "inv-7"
        return web.json_response({"id": "inv-7", "status": "completed"})

    server, client = await _serve([("GET", "/api/v1/invoices/{iid}", handler)])
    try:
        assert await client.invoice_status("inv-7") == "completed"
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_unreachable_host_is_lava_error():
    client = LavaClient("k", base_url="http://127.0.0.1:9", timeout=2)
    with pytest.raises(LavaError):
        await client.invoice_status("inv-1")


def test_from_env(monkeypatch):
    monkeypatch.delenv("LAVA_API_KEY", raising=False)
    assert LavaClient.from_env() is None
    monkeypatch.setenv("LAVA_API_KEY", "  k  ")
    assert LavaClient.from_env() is not None
