from pydantic import BaseModel, condecimal
from decimal import Decimal
import uuid
from enum import Enum


class OperationType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"


class OperationRequest(BaseModel):
    operation_type: OperationType
    amount: condecimal(gt=0, decimal_places=2)


class WalletResponse(BaseModel):
    wallet_uuid: uuid.UUID
    balance: Decimal
