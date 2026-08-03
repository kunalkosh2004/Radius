import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import SelfMessageNotAllowedError, UserNotFoundError
from app.models import Message
from app.services.message import MessageService


class FakeMessageRepository:
    def __init__(self, latest=None, unread=None, by_id=None) -> None:
        self.messages: list[Message] = []
        self._latest = latest or {}
        self._unread = unread or {}
        self._by_id = by_id or {}

    async def create(self, message: Message) -> Message:
        if message.id is None:
            message.id = uuid.uuid4()
        self.messages.append(message)
        return message

    async def get_conversation(self, me, peer, before, limit):
        return []

    async def get_many(self, message_ids):
        return {mid: self._by_id[mid] for mid in message_ids if mid in self._by_id}

    async def mark_read(self, message_ids, by_user):
        return []

    async def list_latest_message_ids(self, user_id):
        return self._latest

    async def unread_counts(self, user_id):
        return self._unread


class FakeUserRepository:
    def __init__(self, *user_ids: uuid.UUID) -> None:
        self.user_ids = set(user_ids)

    async def get_by_id(self, user_id: uuid.UUID):
        if user_id not in self.user_ids:
            return None
        return user_id

    async def get_many(self, user_ids):
        return {uid: uid for uid in user_ids if uid in self.user_ids}


def make_service(*user_ids: uuid.UUID) -> MessageService:
    return MessageService(
        repository=FakeMessageRepository(),
        user_repository=FakeUserRepository(*user_ids),
    )


async def test_send_message_self_not_allowed():
    me = uuid.uuid4()
    service = make_service(me)

    with pytest.raises(SelfMessageNotAllowedError):
        await service.send_message(me, me, "hello me")


async def test_send_message_unknown_recipient_raises():
    service = make_service(uuid.uuid4())

    with pytest.raises(UserNotFoundError):
        await service.send_message(uuid.uuid4(), uuid.uuid4(), "hello?")


async def test_send_message_persists():
    alice, bob = uuid.uuid4(), uuid.uuid4()
    service = make_service(alice, bob)

    message = await service.send_message(alice, bob, "  hello bob  ")

    assert message.sender_id == alice
    assert message.recipient_id == bob
    assert message.body == "  hello bob  "


async def test_get_conversation_unknown_user_raises():
    service = make_service()

    with pytest.raises(UserNotFoundError):
        await service.get_conversation(uuid.uuid4(), uuid.uuid4())


async def test_list_conversations_sorts_by_latest_activity_with_unread():
    alice, bob, carol = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    bob_msg = Message(
        id=uuid.uuid4(),
        sender_id=bob,
        recipient_id=alice,
        body="older",
        created_at=now,
    )
    carol_msg = Message(
        id=uuid.uuid4(),
        sender_id=carol,
        recipient_id=alice,
        body="newer",
        created_at=now + timedelta(seconds=5),
    )
    service = MessageService(
        repository=FakeMessageRepository(
            latest={bob: bob_msg.id, carol: carol_msg.id},
            unread={bob: 2},
            by_id={bob_msg.id: bob_msg, carol_msg.id: carol_msg},
        ),
        user_repository=FakeUserRepository(alice, bob, carol),
    )

    conversations = await service.list_conversations(alice)

    assert [c[0] for c in conversations] == [carol, bob]  # newest first
    assert [c[1] for c in conversations] == [carol_msg, bob_msg]
    assert [c[2] for c in conversations] == [0, 2]  # unread counts


async def test_list_conversations_empty():
    alice = uuid.uuid4()
    service = make_service(alice)

    assert await service.list_conversations(alice) == []


async def test_list_conversations_unknown_user_raises():
    service = make_service()

    with pytest.raises(UserNotFoundError):
        await service.list_conversations(uuid.uuid4())
