import pytest
import pytest_asyncio
from aiogram import Dispatcher

import database
from database import init_db, close_db
from handlers import setup_routers
from middlewares import CallbackSafetyMiddleware, EventLoggingMiddleware


@pytest_asyncio.fixture
async def db():
    await init_db("sqlite+aiosqlite:///:memory:")
    yield
    await close_db()
    database.engine = None
    database.async_session = None


# aiogram Router-объекты в handlers/*.py — модульные синглтоны: include_router
# намертво привязывает router.parent_router и падает RuntimeError при повторном
# include_router() того же router в другой Dispatcher. setup_routers() поэтому
# можно безопасно вызвать только один раз за процесс — dp собираем на весь
# процесс тестов. Живёт в conftest.py (а не в test_booking_flow.py), потому что
# несколько тестовых файлов (test_booking_flow.py, test_reschedule.py, ...)
# переиспользуют один и тот же харнес: scope="session" фикстура, объявленная
# в самом тестовом модуле и импортированная в другой, кэшируется ОТДЕЛЬНО на
# каждый модуль (у pytest получаются разные FixtureDef на одну и ту же
# функцию) — второй модуль вызвал бы setup_routers() повторно и упал. Фикстура
# в conftest.py — одна на весь каталог тестов, инстанс истинно один на сессию.
@pytest.fixture(scope="session")
def _dp():
    dp = Dispatcher()
    dp.callback_query.outer_middleware(CallbackSafetyMiddleware())
    dp.callback_query.outer_middleware(EventLoggingMiddleware())
    dp.message.outer_middleware(EventLoggingMiddleware())
    dp.include_router(setup_routers())
    return dp
