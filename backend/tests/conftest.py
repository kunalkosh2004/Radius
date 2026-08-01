import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://radius:radius123@localhost:5435/radius_test"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "false"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def prepare_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture(scope="session", autouse=True)
async def dispose_engine() -> None:
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
