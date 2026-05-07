import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import uuid
import asyncio

from app.main import app
from app.database import Base, get_db
from app.models import Wallet

ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
TEST_DB = "test_wallets_db"
TEST_URL = f"postgresql+asyncpg://postgres:postgres@localhost:5432/{TEST_DB}"

engine = create_async_engine(TEST_URL)
TestSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def fake_db():
    async with TestSession() as session:
        yield session


app.dependency_overrides[get_db] = fake_db


@pytest.fixture(scope="session", autouse=True)
def manage_db():
    import subprocess
    subprocess.run(f'docker exec -i wallet_app-db-1 psql -U postgres -c "CREATE DATABASE {TEST_DB}"', shell=True)
    asyncio.run(create_tables())
    yield
    asyncio.run(drop_tables())
    subprocess.run(f'docker exec -i wallet_app-db-1 psql -U postgres -c "DROP DATABASE {TEST_DB}"', shell=True)


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
async def clean_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def wallet():
    wid = uuid.uuid4()
    async with TestSession() as session:
        session.add(Wallet(id=wid, balance=0))
        await session.commit()
    return wid


@pytest.mark.asyncio
async def test_get_balance_ok(client, wallet):
    r = await client.get(f"/api/v1/wallets/{wallet}")
    assert r.status_code == 200
    assert r.json()["balance"] == 0


@pytest.mark.asyncio
async def test_get_balance_404(client):
    r = await client.get(f"/api/v1/wallets/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_deposit_ok(client, wallet):
    r = await client.post(f"/api/v1/wallets/{wallet}/operation", json={"operation_type": "DEPOSIT", "amount": 100})
    assert r.status_code == 200
    assert r.json()["balance"] == 100


@pytest.mark.asyncio
async def test_withdraw_ok(client, wallet):
    await client.post(f"/api/v1/wallets/{wallet}/operation", json={"operation_type": "DEPOSIT", "amount": 100})
    r = await client.post(f"/api/v1/wallets/{wallet}/operation", json={"operation_type": "WITHDRAW", "amount": 40})
    assert r.status_code == 200
    assert r.json()["balance"] == 60


@pytest.mark.asyncio
async def test_withdraw_insufficient(client, wallet):
    r = await client.post(f"/api/v1/wallets/{wallet}/operation", json={"operation_type": "WITHDRAW", "amount": 10})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_deposit_negative(client, wallet):
    r = await client.post(f"/api/v1/wallets/{wallet}/operation", json={"operation_type": "DEPOSIT", "amount": -5})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_concurrent(client, wallet):
    await client.post(f"/api/v1/wallets/{wallet}/operation", json={"operation_type": "DEPOSIT", "amount": 100})
    tasks = [client.post(f"/api/v1/wallets/{wallet}/operation", json={"operation_type": "WITHDRAW", "amount": 10}) for _
             in range(10)]
    responses = await asyncio.gather(*tasks)
    assert all(r.status_code == 200 for r in responses)
    r = await client.get(f"/api/v1/wallets/{wallet}")
    assert r.json()["balance"] == 0
