from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.user import UserRead


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_id: UUID
    recipient_id: UUID
    body: str
    read_at: datetime | None
    created_at: datetime


class ConversationRead(BaseModel):
    peer: UserRead
    last_message: MessageRead
    unread_count: int
