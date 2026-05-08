import uuid
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, condecimal


class OperationType(str, Enum):
    """
    Тип операции с кошельком.

    Attributes:
        DEPOSIT: Пополнение баланса.
        WITHDRAW: Снятие средств с баланса.
    """

    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"


class OperationRequest(BaseModel):
    """
    Схема запроса на выполнение операции с кошельком.

    Attributes:
        operation_type: Тип операции (DEPOSIT или WITHDRAW).
        amount: Сумма операции, строго больше нуля,
            с точностью до двух знаков после запятой.
    """

    operation_type: OperationType
    amount: condecimal(gt=0, decimal_places=2)


class WalletResponse(BaseModel):
    """
    Схема ответа с информацией о кошельке.

    Attributes:
        wallet_uuid: Уникальный идентификатор кошелька.
        balance: Текущий баланс кошелька.
    """

    wallet_uuid: uuid.UUID
    balance: Decimal
