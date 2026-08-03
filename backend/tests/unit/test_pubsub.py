import json
from uuid import uuid4

from app.core.pubsub import EVENTS_CHANNEL, publish
from app.websocket.manager import ConnectionManager


class StubSocket:
    """A socket that records what it was told to send."""

    def __init__(self) -> None:
        self.received: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.received.append(data)


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))


async def test_publish_sends_envelope_and_delivers_locally():
    redis = FakeRedis()
    manager = ConnectionManager()
    target = uuid4()
    socket = StubSocket()
    manager.add(target, socket)

    await publish(redis, manager, [target], {"type": "test"}, origin="instance-x")

    assert socket.received == [{"type": "test"}]

    (channel, raw), = redis.published
    assert channel == EVENTS_CHANNEL
    envelope = json.loads(raw)
    assert envelope["origin"] == "instance-x"
    assert envelope["to"] == [str(target)]
    assert envelope["payload"] == {"type": "test"}


async def test_publish_sends_envelope_even_with_no_local_sockets():
    redis = FakeRedis()
    manager = ConnectionManager()
    target = uuid4()

    await publish(redis, manager, [target], {"type": "test"})

    (_, raw), = redis.published
    assert json.loads(raw)["to"] == [str(target)]
