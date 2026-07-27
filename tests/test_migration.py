import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from database import Booking, get_session, init_db, close_db
import database


@pytest.mark.asyncio
async def test_reschedule_columns_exist():
    await init_db("sqlite+aiosqlite:///:memory:")
    async with get_session() as s:
        s.add(Booking(
            telegram_id=1,
            slot_start=datetime(2026, 7, 28, 10, tzinfo=timezone.utc),
            reschedule_to=datetime(2026, 7, 29, 10, tzinfo=timezone.utc),
            reschedule_reason="заболела",
            reschedule_status="pending",
        ))
        await s.commit()
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.reschedule_status == "pending"
    assert b.reschedule_reason == "заболела"
    await close_db()
    database.engine = None
    database.async_session = None
