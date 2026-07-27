import pytest
import pytest_asyncio

import database
from database import init_db, close_db


@pytest_asyncio.fixture
async def db():
    await init_db("sqlite+aiosqlite:///:memory:")
    yield
    await close_db()
    database.engine = None
    database.async_session = None
