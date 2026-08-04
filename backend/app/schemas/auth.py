from uuid import UUID

from pydantic import BaseModel


class WsTokenRequest(BaseModel):
    user_id: UUID


class WsTokenResponse(BaseModel):
    token: str
    expires_in: int
    user_id: UUID
