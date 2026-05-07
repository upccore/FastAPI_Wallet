import os
import uuid
from decimal import Decimal

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import Wallet

TEST_USER = os.getenv("POSTGRES_USER", "postgres")
TEST_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
TEST_HOST = os.getenv("POSTGRES_HOST", "localhost")
TEST_PORT = os.getenv("POSTGRES_PORT", "5432")
TEST_DB = "wallets_test_db"
TEST_URL = f"postgresql+asyncpg://{TEST_USER}:{TEST_PASSWORD}@{TEST_HOST}:{TEST_PORT}/{TEST_DB}"


async def create_test_database():
    try:
        conn = await asyncpg.connect(
            user=TEST_USER,
            password=TEST_PASSWORD,
            host=TEST_HOST,
            port=TEST_PORT,
            database="postgres"
        )
        await conn.execute(f"CREATE DATABASE {TEST_DB}")
        await conn.close()
    except asyncpg.exceptions.DuplicateDatabaseError:
        pass
    except Exception:
        pass


@pytest_asyncio.fixture
async def engine():
    await create_test_database()

    engine = create_async_engine(TEST_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def override_dependency(session):
    async def fake_db():
        yield session

    app.dependency_overrides[get_db] = fake_db
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def wallet(session):
    wid = uuid.uuid4()
    wallet = Wallet(id=wid, balance=0)
    session.add(wallet)
    await session.commit()
    return wid


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_get_balance_ok(client, wallet):
    r = await client.get(f"/api/v1/wallets/{wallet}")
    assert r.status_code == 200
    assert Decimal(r.json()["balance"]) == 0


@pytest.mark.asyncio
async def test_get_balance_404(client):
    r = await client.get(f"/api/v1/wallets/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_deposit_ok(client, wallet):
    r = await client.post(
        f"/api/v1/wallets/{wallet}/operation",
        json={"operation_type": "DEPOSIT", "amount": 100},
    )
    assert r.status_code == 200
    assert Decimal(r.json()["balance"]) == 100


@pytest.mark.asyncio
async def test_withdraw_ok(client, wallet):
    await client.post(
        f"/api/v1/wallets/{wallet}/operation",
        json={"operation_type": "DEPOSIT", "amount": 100},
    )
    r = await client.post(
        f"/api/v1/wallets/{wallet}/operation",
        json={"operation_type": "WITHDRAW", "amount": 40},
    )
    assert r.status_code == 200
    assert Decimal(r.json()["balance"]) == 60


@pytest.mark.asyncio
async def test_withdraw_insufficient(client, wallet):
    r = await client.post(
        f"/api/v1/wallets/{wallet}/operation",
        json={"operation_type": "WITHDRAW", "amount": 10},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_deposit_negative(client, wallet):
    r = await client.post(
        f"/api/v1/wallets/{wallet}/operation",
        json={"operation_type": "DEPOSIT", "amount": -5},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_concurrent(client, wallet):
    await client.post(
        f"/api/v1/wallets/{wallet}/operation",
        json={"operation_type": "DEPOSIT", "amount": 100},
    )
    tasks = [
        client.post(
            f"/api/v1/wallets/{wallet}/operation",
            json={"operation_type": "WITHDRAW", "amount": 10},
        )
        for _ in range(9)
    ]
    responses = [await task for task in tasks]
    assert all(r.status_code == 200 for r in responses)
    r = await client.get(f"/api/v1/wallets/{wallet}")
    assert Decimal(r.json()["balance"]) == 10
