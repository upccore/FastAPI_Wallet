import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Wallet
from .schemas import OperationRequest


async def get_wallet(db: AsyncSession, wallet_id: uuid.UUID):
    result = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    return result.scalar_one_or_none()


async def process_operation(
    db: AsyncSession, wallet_id: uuid.UUID, operation: OperationRequest
):
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
