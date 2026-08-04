from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import UserNotFoundError
from app.core.ws_token import create_ws_token
from app.db.dependencies import get_db
from app.repositories.user import UserRepository
from app.schemas.auth import WsTokenRequest, WsTokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

settings = get_settings()


@router.post("/ws-token", response_model=WsTokenResponse)
async def create_ws_token_endpoint(
    payload: WsTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> WsTokenResponse:
    """Issue a short-lived signed token for a websocket connection."""
    user = await UserRepository(db).get_by_id(payload.user_id)
    if user is None:
        raise UserNotFoundError()

    return WsTokenResponse(
        token=create_ws_token(payload.user_id),
        expires_in=settings.WS_TOKEN_TTL_S,
        user_id=payload.user_id,
    )
