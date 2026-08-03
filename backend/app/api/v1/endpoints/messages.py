from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db
from app.models import Message
from app.repositories.message import MessageRepository
from app.repositories.user import UserRepository
from app.schemas.message import MessageRead
from app.services.message import MessageService

router = APIRouter(prefix="/users/{user_id}/messages", tags=["messages"])


async def get_message_service(
    db: AsyncSession = Depends(get_db),
) -> MessageService:
    return MessageService(MessageRepository(db), UserRepository(db))


@router.get("/{peer_id}", response_model=list[MessageRead])
async def get_conversation(
    user_id: UUID,
    peer_id: UUID,
    before: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    service: MessageService = Depends(get_message_service),
) -> list[Message]:
    """Newest-first history between user_id and peer_id (both directions)."""
    return await service.get_conversation(user_id, peer_id, before, limit)
