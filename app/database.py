from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=True)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Генератор зависимостей FastAPI для получения сессии БД.

    Создаёт новую асинхронную сессию для каждого HTTP-запроса
    и автоматически закрывает её после обработки.

    Yields:
        AsyncSession: Асинхронная сессия SQLAlchemy.
    """
    async with async_session() as session:
        yield session
