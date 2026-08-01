from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=30)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nickname: str
    latitude: float
    longitude: float
    is_online: bool
    last_seen: datetime | None
    created_at: datetime
    updated_at: datetime
