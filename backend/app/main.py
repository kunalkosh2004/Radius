from fastapi import Depends, FastAPI

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db

app = FastAPI(
    title="Radius API",
    version="0.1.0",
)


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))

    return {
        "status": "healthy",
        "database": result.scalar(),
    }