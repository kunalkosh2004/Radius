import uuid

import pytest

from app.core.exceptions import SelfMessageNotAllowedError, UserNotFoundError
from app.models import Message
from app.services.message import MessageService


class FakeMessageRepository:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def create(self, message: Message) -> Message:
        if message.id is None:
            message.id = uuid.uuid4()
        self.messages.append(message)
        return message

    async def get_conversation(self, me, peer, before, limit):
        return []


class FakeUserRepository:
    def __init__(self, *user_ids: uuid.UUID) -> None:
        self.user_ids = set(user_ids)

    async def get_by_id(self, user_id: uuid.UUID):
        if user_id not in self.user_ids:
            return None
        return user_id


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
