from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    func,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

engine = None
async_session: async_sessionmaker[AsyncSession] | None = None


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id")
    )
    name: Mapped[str] = mapped_column(String(255))
    contact_info: Mapped[str] = mapped_column(String(255))
    request_text: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(50), default="new")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Booking(Base):
    """Запись на слот. Статусы:
    held — слот держится за клиентом на время оплаты (held_until);
    pay_claimed — нажал «Я оплатил(а)», событие в календаре создано;
    confirmed — Лана подтвердила; cancelled — Лана отклонила / отменено."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="held")
    held_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    google_event_id: Mapped[str | None] = mapped_column(String(1024))
    calendar_sync_failed: Mapped[bool] = mapped_column(default=False)
    reschedule_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reschedule_reason: Mapped[str | None] = mapped_column(String(500))
    reschedule_status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Идемпотентные ALTER для полей, добавленных после первого create_all.
# create_all создаёт только отсутствующие таблицы, но не добавляет колонки в
# существующие — на Postgres их доводим здесь. sqlite (тесты) получает полную
# схему сразу через create_all, поэтому миграции для него не нужны.
_MIGRATIONS = [
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reschedule_to TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reschedule_reason VARCHAR(500)",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reschedule_status VARCHAR(20)",
]


async def init_db(database_url: str) -> None:
    global engine, async_session
    # Railway provides postgresql:// but asyncpg needs postgresql+asyncpg://
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(database_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            for ddl in _MIGRATIONS:
                await conn.execute(text(ddl))


def get_session() -> AsyncSession:
    if async_session is None:
        raise RuntimeError("Database is not initialized — call init_db() first")
    return async_session()


async def get_setting(key: str) -> str | None:
    async with get_session() as session:
        setting = await session.get(Setting, key)
        return setting.value if setting else None


async def set_setting(key: str, value: str) -> None:
    async with get_session() as session:
        setting = await session.get(Setting, key)
        if setting:
            setting.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()


async def del_setting(key: str) -> None:
    async with get_session() as session:
        setting = await session.get(Setting, key)
        if setting:
            await session.delete(setting)
            await session.commit()


async def close_db() -> None:
    global engine
    if engine:
        await engine.dispose()
