from uuid import UUID

from app.core.config import get_settings
from app.core.exceptions import SelfMessageNotAllowedError, UserNotFoundError
from app.models import Message, User
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

    async def mark_read(
        self, by_user: UUID, message_ids: list[UUID]
    ) -> list[Message]:
        """Mark received messages as read. Returns the ones actually marked."""
        if not message_ids:
            return []
        return await self._repository.mark_read(message_ids, by_user)

    async def list_conversations(
        self, user_id: UUID
    ) -> list[tuple[User, Message, int]]:
        """(peer, latest message, unread count) per peer, newest activity first."""
        user = await self._user_repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()

        latest = await self._repository.list_latest_message_ids(user_id)
        if not latest:
            return []

        peer_ids = list(latest.keys())
        messages = await self._repository.get_many(list(latest.values()))
        peers = await self._user_repository.get_many(peer_ids)
        unread = await self._repository.unread_counts(user_id)

        conversations = [
            (peers[peer_id], messages[message_id], unread.get(peer_id, 0))
            for peer_id, message_id in latest.items()
        ]
        conversations.sort(key=lambda c: c[1].created_at, reverse=True)
        return conversations
