import pytest
from datetime import datetime, timedelta, timezone
from database import init_db, close_db, get_session, Booking, Event
import database
from followup import reminder_pass


class FakeBot:
    def __init__(self): self.sent = []
    async def send_message(self, uid, text, reply_markup=None):
        self.sent.append((uid, text))


@pytest.mark.asyncio
async def test_reminder_sent_once_for_tomorrow_session():
    await init_db("sqlite+aiosqlite:///:memory:")
    now = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
    async with get_session() as s:
        s.add(Booking(telegram_id=1, slot_start=now + timedelta(hours=23),
                      status="confirmed"))  # завтра
        s.add(Booking(telegram_id=2, slot_start=now + timedelta(days=5),
                      status="confirmed"))  # далеко
        await s.commit()
    bot = FakeBot()
    n1 = await reminder_pass(bot, now)
    n2 = await reminder_pass(bot, now)  # повторно не шлём
    assert n1 == 1 and n2 == 0
    assert bot.sent[0][0] == 1
    await close_db()
    database.engine = None
    database.async_session = None
