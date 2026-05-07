import asyncio
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import Wallet

TEST_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/wallets_db"


class TestWalletAPI:

    @pytest.fixture(scope="class")
    def event_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        yield loop
        loop.close()

    @pytest.fixture(autouse=True)
    async def _setup(self):
        self.engine = create_async_engine(TEST_URL)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def fake_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = fake_db
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

        yield

        await self.client.aclose()
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await self.engine.dispose()

    @pytest.fixture
    async def wallet(self):
        wid = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(Wallet(id=wid, balance=0))
            await session.commit()
        return wid

    @pytest.mark.asyncio
    async def test_get_balance_ok(self, wallet):
        r = await self.client.get(f"/api/v1/wallets/{wallet}")
        assert r.status_code == 200
        assert Decimal(r.json()["balance"]) == 0

    @pytest.mark.asyncio
    async def test_get_balance_404(self):
        r = await self.client.get(f"/api/v1/wallets/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_deposit_ok(self, wallet):
        r = await self.client.post(
            f"/api/v1/wallets/{wallet}/operation",
            json={"operation_type": "DEPOSIT", "amount": 100},
        )
        assert r.status_code == 200
        assert Decimal(r.json()["balance"]) == 100

    @pytest.mark.asyncio
    async def test_withdraw_ok(self, wallet):
        await self.client.post(
            f"/api/v1/wallets/{wallet}/operation",
            json={"operation_type": "DEPOSIT", "amount": 100},
        )
        r = await self.client.post(
            f"/api/v1/wallets/{wallet}/operation",
            json={"operation_type": "WITHDRAW", "amount": 40},
        )
        assert r.status_code == 200
        assert Decimal(r.json()["balance"]) == 60

    @pytest.mark.asyncio
    async def test_withdraw_insufficient(self, wallet):
        r = await self.client.post(
            f"/api/v1/wallets/{wallet}/operation",
            json={"operation_type": "WITHDRAW", "amount": 10},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_deposit_negative(self, wallet):
        r = await self.client.post(
            f"/api/v1/wallets/{wallet}/operation",
            json={"operation_type": "DEPOSIT", "amount": -5},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_concurrent(self, wallet):
        await self.client.post(
            f"/api/v1/wallets/{wallet}/operation",
            json={"operation_type": "DEPOSIT", "amount": 100},
        )
        tasks = [
            self.client.post(
                f"/api/v1/wallets/{wallet}/operation",
                json={"operation_type": "WITHDRAW", "amount": 10},
            )
            for _ in range(10)
        ]
        responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)
        r = await self.client.get(f"/api/v1/wallets/{wallet}")
        assert Decimal(r.json()["balance"]) == 0
