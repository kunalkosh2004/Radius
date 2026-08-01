from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db.dependencies import get_db

settings = get_settings()

app = FastAPI(
    title="Radius API",
    version="0.1.0",
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))

    return {
        "status": "healthy",
        "database": result.scalar(),
    }
