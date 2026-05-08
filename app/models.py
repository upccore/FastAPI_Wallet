import uuid

from sqlalchemy import Column, Numeric
from sqlalchemy.dialects.postgresql import UUID

from .database import Base


class Wallet(Base):
    """
    Модель кошелька.

    Attributes:
        id: Уникальный идентификатор кошелька.
        balance: Текущий баланс кошелька. По умолчанию 0.00.
    """

    __tablename__ = "wallets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    balance = Column(Numeric(10, 2), default=0.00, nullable=False)
