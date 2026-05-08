import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud, schemas
from .database import engine, get_db
from .models import Wallet


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Контекстный менеджер жизненного цикла приложения.

    При старте передаёт управление приложению,
    при завершении освобождает соединения с базой данных.

    Args:
        app: Экземпляр FastAPI-приложения.

    Yields:
        None: Управление возвращается приложению.
    """
    yield
    await engine.dispose()


app = FastAPI(title="Wallet Service", lifespan=lifespan)


@app.post(
    "/api/v1/wallets/{WALLET_UUID}/operation", response_model=schemas.WalletResponse
)
async def wallet_operation(
    WALLET_UUID: uuid.UUID,
    operation: schemas.OperationRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Выполнить операцию пополнения или снятия средств с кошелька.

    Поддерживает два типа операций:
    - DEPOSIT: пополнение баланса на указанную сумму.
    - WITHDRAW: снятие средств с баланса (при достаточном остатке).

    Args:
        WALLET_UUID: UUID кошелька, с которым производится операция.
        operation: Данные операции (тип и сумма).
        db: Асинхронная сессия БД (внедряется через Depends).

    Returns:
        dict: JSON с UUID кошелька и обновлённым балансом.

    Raises:
        HTTPException 404: Если кошелёк с указанным UUID не найден.
        HTTPException 400: Если недостаточно средств для снятия.
    """
    result = await crud.process_operation(db, WALLET_UUID, operation)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet not found")
    if result == "INSUFFICIENT_FUNDS":
        raise HTTPException(status_code=400, detail="Insufficient funds")
    return {"wallet_uuid": result.id, "balance": result.balance}


@app.get("/api/v1/wallets/{WALLET_UUID}", response_model=schemas.WalletResponse)
async def get_balance(
    WALLET_UUID: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Получить текущий баланс кошелька по его UUID.

    Args:
        WALLET_UUID: UUID кошелька для запроса баланса.
        db: Асинхронная сессия БД (внедряется через Depends).

    Returns:
        dict: JSON с UUID кошелька и текущим балансом.

    Raises:
        HTTPException 404: Если кошелёк с указанным UUID не найден.
    """
    wallet = await crud.get_wallet(db, WALLET_UUID)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return {"wallet_uuid": wallet.id, "balance": wallet.balance}
