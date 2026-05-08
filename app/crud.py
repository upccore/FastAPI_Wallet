import uuid
from typing import Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Wallet
from .schemas import OperationRequest


async def get_wallet(db: AsyncSession, wallet_id: uuid.UUID) -> Optional[Wallet]:
    """
    Получить кошелёк по его UUID.

    Args:
        db: Асинхронная сессия SQLAlchemy.
        wallet_id: UUID кошелька для поиска.

    Returns:
        Optional[Wallet]: Объект кошелька, если найден, иначе None.
    """
    result = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    return result.scalar_one_or_none()


async def process_operation(
    db: AsyncSession, wallet_id: uuid.UUID, operation: OperationRequest
) -> Optional[Union[Wallet, str]]:
    """
    Обработать операцию пополнения или снятия средств.

    Использует блокировку строки (SELECT ... FOR UPDATE) для обеспечения
    целостности данных при конкурентных запросах.
    Выполняется в отдельной транзакции.

    Args:
        db: Асинхронная сессия SQLAlchemy.
        wallet_id: UUID кошелька, над которым выполняется операция.
        operation: Pydantic-схема с типом операции и суммой.

    Returns:
        Optional[Union[Wallet, str]]:
            - Объект Wallet с обновлённым балансом при успешной операции.
            - None, если кошелёк не найден.
            - Строку "INSUFFICIENT_FUNDS", если недостаточно средств для снятия.
    """
    async with db.begin():
        result = await db.execute(
            select(Wallet).where(Wallet.id == wallet_id).with_for_update()
        )
        wallet = result.scalar_one_or_none()
        if not wallet:
            return None

        if operation.operation_type == "DEPOSIT":
            wallet.balance += operation.amount
        elif operation.operation_type == "WITHDRAW":
            if wallet.balance < operation.amount:
                return "INSUFFICIENT_FUNDS"
            wallet.balance -= operation.amount

    return wallet
