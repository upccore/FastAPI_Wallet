import os
import uuid
from decimal import Decimal
from typing import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base, get_db
from app.main import app
from app.models import Wallet

TEST_USER = os.getenv("POSTGRES_USER", "postgres")
TEST_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
TEST_HOST = os.getenv("POSTGRES_HOST", "localhost")
TEST_PORT = os.getenv("POSTGRES_PORT", "5432")
TEST_DB = "wallets_test_db"
TEST_URL = f"postgresql+asyncpg://{TEST_USER}:{TEST_PASSWORD}@{TEST_HOST}:{TEST_PORT}/{TEST_DB}"


async def create_test_database() -> None:
    """
    Создать тестовую базу данных, если она ещё не существует.

    Подключается к системной базе 'postgres' и выполняет
    CREATE DATABASE. Игнорирует ошибку, если БД уже создана.
    """
    try:
        conn = await asyncpg.connect(
            user=TEST_USER,
            password=TEST_PASSWORD,
            host=TEST_HOST,
            port=TEST_PORT,
            database="postgres",
        )
        await conn.execute(f"CREATE DATABASE {TEST_DB}")
        await conn.close()
    except asyncpg.exceptions.DuplicateDatabaseError:
        pass
    except Exception:
        pass


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """
    Фикстура Pytest, создающая и удаляющая таблицы перед тестами.

    Создаёт тестовую БД, все таблицы по моделям Base,
    а после завершения тестов удаляет таблицы и закрывает движок.

    Yields:
        AsyncEngine: Асинхронный движок SQLAlchemy для тестовой БД.
    """
    await create_test_database()

    engine = create_async_engine(TEST_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Фикстура Pytest, предоставляющая чистую сессию БД для каждого теста.

    Args:
        engine: Фикстура асинхронного движка.

    Yields:
        AsyncSession: Асинхронная сессия SQLAlchemy.
    """
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def override_dependency(session) -> AsyncGenerator[None, None]:
    """
    Фикстура, автоматически подменяющая зависимость get_db на тестовую сессию.

    Гарантирует, что все эндпоинты во время тестов используют
    тестовую базу данных, а не продакшен.

    Args:
        session: Фикстура тестовой сессии БД.
    """

    async def fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_db] = fake_db
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def wallet(session) -> uuid.UUID:
    """
    Фикстура, создающая тестовый кошелёк с нулевым балансом.

    Args:
        session: Фикстура тестовой сессии БД.

    Returns:
        uuid.UUID: UUID созданного кошелька.
    """
    wid = uuid.uuid4()
    wallet = Wallet(id=wid, balance=0)
    session.add(wallet)
    await session.commit()
    return wid


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    Фикстура, предоставляющая асинхронный HTTP-клиент для тестирования API.

    Использует ASGITransport для прямого обращения к приложению
    без поднятия реального сервера.

    Yields:
        AsyncClient: Асинхронный клиент httpx.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_get_balance_ok(client, wallet) -> None:
    """
    Тест: успешное получение баланса существующего кошелька.

    Ожидается статус 200 и баланс 0.

    Args:
        client: Фикстура HTTP-клиента.
        wallet: Фикстура с UUID тестового кошелька.
    """
    r = await client.get(f"/api/v1/wallets/{wallet}")
    assert r.status_code == 200
    assert Decimal(r.json()["balance"]) == 0


@pytest.mark.asyncio
async def test_get_balance_404(client) -> None:
    """
    Тест: запрос баланса несуществующего кошелька.

    Ожидается статус 404.

    Args:
        client: Фикстура HTTP-клиента.
    """
    r = await client.get(f"/api/v1/wallets/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_deposit_ok(client, wallet) -> None:
    """
    Тест: успешное пополнение баланса кошелька.

    Пополняет на 100 и проверяет, что баланс стал равен 100.

    Args:
        client: Фикстура HTTP-клиента.
        wallet: Фикстура с UUID тестового кошелька.
    """
    r = await client.post(
        f"/api/v1/wallets/{wallet}/operation",
        json={"operation_type": "DEPOSIT", "amount": 100},
    )
    assert r.status_code == 200
    assert Decimal(r.json()["balance"]) == 100


@pytest.mark.asyncio
async def test_withdraw_ok(client, wallet) -> None:
    """
    Тест: успешное снятие средств после пополнения.

    Пополняет на 100, затем снимает 40, ожидает баланс 60.

    Args:
        client: Фикстура HTTP-клиента.
        wallet: Фикстура с UUID тестового кошелька.
    """
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
async def test_withdraw_insufficient(client, wallet) -> None:
    """
    Тест: попытка снятия при недостатке средств.

    Кошелёк имеет баланс 0, запрос на снятие 10 должен вернуть 400.

    Args:
        client: Фикстура HTTP-клиента.
        wallet: Фикстура с UUID тестового кошелька.
    """
    r = await client.post(
        f"/api/v1/wallets/{wallet}/operation",
        json={"operation_type": "WITHDRAW", "amount": 10},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_deposit_negative(client, wallet) -> None:
    """
    Тест: попытка пополнения на отрицательную сумму.

    Ожидается статус 422 (ошибка валидации Pydantic).

    Args:
        client: Фикстура HTTP-клиента.
        wallet: Фикстура с UUID тестового кошелька.
    """
    r = await client.post(
        f"/api/v1/wallets/{wallet}/operation",
        json={"operation_type": "DEPOSIT", "amount": -5},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_concurrent(client, wallet) -> None:
    """
    Тест: конкурентные запросы на снятие средств.

    Пополняет баланс на 100, затем отправляет 9 параллельных
    запросов на снятие по 10. Ожидается, что все запросы успешны
    и итоговый баланс равен 10.

    Args:
        client: Фикстура HTTP-клиента.
        wallet: Фикстура с UUID тестового кошелька.
    """
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
