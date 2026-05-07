import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud, schemas
from .database import engine, get_db
from .models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
):
    result = await crud.process_operation(db, WALLET_UUID, operation)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet not found")
    if result == "INSUFFICIENT_FUNDS":
        raise HTTPException(status_code=400, detail="Insufficient funds")
    return {"wallet_uuid": result.id, "balance": result.balance}


@app.get("/api/v1/wallets/{WALLET_UUID}", response_model=schemas.WalletResponse)
async def get_balance(WALLET_UUID: uuid.UUID, db: AsyncSession = Depends(get_db)):
    wallet = await crud.get_wallet(db, WALLET_UUID)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return {"wallet_uuid": wallet.id, "balance": wallet.balance}
