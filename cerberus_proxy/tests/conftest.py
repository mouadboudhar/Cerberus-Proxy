import os
import tempfile

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cerberus_proxy import db
from cerberus_proxy.auth.keys import generate_api_key, hash_key
from cerberus_proxy.auth.models import Base
from cerberus_proxy.auth.repository import SQLiteKeyRepository
from cerberus_proxy.proxy.main import app


@pytest_asyncio.fixture
async def session_factory(monkeypatch):
    """File-backed SQLite engine, with cerberus_proxy.db patched so the middleware uses it.

    A file gives each session its own connection (real transaction isolation). An
    in-memory StaticPool shares ONE connection across every session, so the proxy's
    fire-and-forget audit writes get rolled back by another session's transaction
    boundary on that shared connection — the source of the flaky audit tests.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "AsyncSessionLocal", factory)
    yield factory
    await engine.dispose()
    os.unlink(path)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def create_key(session_factory):
    """Returns an async helper: await create_key("name") -> (plaintext, id)."""

    async def _make(name: str = "app") -> tuple[str, int]:
        plaintext = generate_api_key()
        async with session_factory() as session:
            repo = SQLiteKeyRepository(session)
            key = await repo.create(name=name, key_hash=hash_key(plaintext))
            await session.commit()
            return plaintext, key.id

    return _make
