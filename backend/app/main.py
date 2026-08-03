import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.background import presence_sweeper
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.pubsub import subscribe
from app.core.redis import get_redis
from app.db.dependencies import get_db
from app.websocket.router import (
    manager,
    nearby_broadcaster,
    router as ws_router,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [
        asyncio.create_task(presence_sweeper()),
        asyncio.create_task(nearby_broadcaster()),
        asyncio.create_task(subscribe(get_redis(), manager)),
    ]
    yield
    for task in tasks:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Radius API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(ws_router)


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
