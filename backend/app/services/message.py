from uuid import UUID

from app.core.config import get_settings
from app.core.exceptions import SelfMessageNotAllowedError, UserNotFoundError
from app.models import Message
from app.repositories.message import MessageRepository
from app.repositories.user import UserRepository

settings = get_settings()


class MessageService:
    def __init__(
        self,
        repository: MessageRepository,
        user_repository: UserRepository,
    ) -> None:
        self._repository = repository
        self._user_repository = user_repository

    async def send_message(
        self, sender_id: UUID, recipient_id: UUID, body: str
    ) -> Message:
        """Validate and persist a single message. Caller owns the transaction."""
        if sender_id == recipient_id:
            raise SelfMessageNotAllowedError()

        recipient = await self._user_repository.get_by_id(recipient_id)
        if recipient is None:
            raise UserNotFoundError()

        return await self._repository.create(
            Message(sender_id=sender_id, recipient_id=recipient_id, body=body)
        )

    async def get_conversation(
        self,
        me: UUID,
        peer: UUID,
        before: UUID | None = None,
        limit: int = settings.MESSAGE_PAGE_SIZE,
    ) -> list[Message]:
        me_user = await self._user_repository.get_by_id(me)
        if me_user is None:
            raise UserNotFoundError()
        peer_user = await self._user_repository.get_by_id(peer)
        if peer_user is None:
            raise UserNotFoundError()

        return await self._repository.get_conversation(me, peer, before, limit)
